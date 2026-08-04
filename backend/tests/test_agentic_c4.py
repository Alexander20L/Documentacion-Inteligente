import json
import threading
import time
import unittest
from unittest.mock import Mock, patch

import httpx
from pydantic import ValidationError

from c4core import ElementKind, Provenance
from agentic_c4 import (
    AgentGraphFragment,
    AgentMetadata,
    AgentOrchestrationError,
    AgentOrchestrator,
    AgentRequest,
    AgentRole,
    CapabilityConsolidationPlan,
    CapabilityGroup,
    FindingSeverity,
    FragmentElement,
    FragmentRelationship,
    JudgeFinding,
    JudgeReport,
    MergedAgentGraph,
    MergedElement,
    MergedRelationship,
    ModuleWork,
    OllamaC4Agent,
    RetrievalChunk,
    apply_consolidation_plan,
    deterministic_judge_report,
    sanitize_consolidation_plan,
    merge_agent_graphs,
    to_c4core_candidates,
    validate_judge_report,
)
from agentic_c4.gemini import (
    agent_response_model,
    agent_response_schema,
    canonical_capability_key,
    deterministic_retrieval_queries,
    evidence_aliases,
    generate_with_retry,
    gemini_json_schema,
    restore_evidence_aliases,
    sanitize_agent_fragment,
    select_whole_chunks,
)


class _GeminiError(Exception):
    def __init__(self, code, details=None):
        self.code = code
        self.details = details
        super().__init__(str(code))


def element(
    local_id: str,
    evidence: str,
    *,
    semantic_key: str | None = None,
    kind: ElementKind = ElementKind.COMPONENT,
    technology: str | None = None,
    parent_ref: str | None = None,
) -> FragmentElement:
    return FragmentElement(
        local_id=local_id,
        kind=kind,
        name=local_id.upper(),
        description=f"Architecture element {local_id}",
        semantic_key=semantic_key,
        technology=technology,
        parent_ref=parent_ref,
        evidence_chunk_ids=(evidence,),
    )


def fragment(
    fragment_id: str,
    module: str,
    elements: tuple[FragmentElement, ...],
    relationships: tuple[FragmentRelationship, ...] = (),
) -> AgentGraphFragment:
    return AgentGraphFragment(
        fragment_id=fragment_id,
        metadata=AgentMetadata(agent_id=f"agent-{module}", role=AgentRole.MODULE, module_id=module, model="fake"),
        elements=elements,
        relationships=relationships,
    )


class MergeTests(unittest.TestCase):
    def test_merge_normalizes_role_specific_element_kind(self) -> None:
        infrastructure = agent_response_model(AgentRole.INFRASTRUCTURE).model_validate_json(json.dumps({
            "fragment_id": "infrastructure",
            "metadata": {
                "agent_id": "infra",
                "role": "infrastructure",
                "module_id": None,
                "model": "qwen3:8b",
            },
            "elements": [{
                "local_id": "api",
                "kind": "container",
                "name": "API",
                "description": "Application HTTP API",
                "parent_ref": "root",
                "evidence_chunk_ids": ["ev"],
            }],
            "relationships": [],
            "unresolved_references": [],
        }))

        merged = merge_agent_graphs((infrastructure,), existing_references={"root": "analyst-system"})

        self.assertEqual(merged.elements[0].kind, ElementKind.CONTAINER)
        self.assertIs(type(merged.elements[0].kind), ElementKind)

    def test_duplicate_merge_is_stable_and_unions_evidence(self) -> None:
        left = fragment("left", "a", (element("api-a", "ev-a", semantic_key="orders.api"),))
        right = fragment("right", "b", (element("renamed", "ev-b", semantic_key="orders.api"),))
        merged = merge_agent_graphs((right, left))
        reversed_merge = merge_agent_graphs((left, right))
        self.assertEqual(merged, reversed_merge)
        self.assertEqual(len(merged.elements), 1)
        self.assertEqual(merged.elements[0].evidence_chunk_ids, ("ev-a", "ev-b"))
        candidates, _ = to_c4core_candidates(merged)
        self.assertEqual(candidates[0].provenance, Provenance.INFERRED)

    def test_incompatible_duplicate_is_conflict_not_candidate(self) -> None:
        left = fragment("left", "a", (element("api", "ev-a", semantic_key="orders.api", technology="FastAPI"),))
        right = fragment("right", "b", (element("api", "ev-b", semantic_key="orders.api", technology="Flask"),))
        merged = merge_agent_graphs((left, right))
        self.assertEqual(merged.elements, ())
        self.assertEqual(len(merged.conflicts), 1)
        self.assertEqual(merged.conflicts[0].kind.value, "technology")

    def test_cross_module_relationship_resolves_and_deduplicates(self) -> None:
        api = fragment("api-fragment", "api", (element("api", "ev-api", semantic_key="orders.api"),))
        relation = FragmentRelationship(
            local_id="calls-db",
            source_ref="orders.api",
            target_ref="orders.db",
            description="stores orders",
            evidence_chunk_ids=("ev-edge",),
        )
        db = fragment("db-fragment", "db", (element("db", "ev-db", semantic_key="orders.db"),), (relation,))
        merged = merge_agent_graphs((db, api))
        self.assertEqual(len(merged.relationships), 1)
        self.assertEqual(merged.orphans, ())
        ids = {item.id for item in merged.elements}
        self.assertIn(merged.relationships[0].source_id, ids)
        self.assertIn(merged.relationships[0].target_id, ids)

    def test_unresolved_parent_is_quarantined(self) -> None:
        child = fragment("child-fragment", "child", (element("child", "ev", parent_ref="missing-parent"),))
        merged = merge_agent_graphs((child,))
        self.assertEqual(merged.elements, ())
        self.assertEqual(len(merged.orphans), 1)
        self.assertEqual(merged.orphans[0].candidate_kind, "element")

    def test_fragment_reference_wins_over_external_alias_collision(self) -> None:
        relation = FragmentRelationship(
            local_id="local-edge", source_ref="root", target_ref="db",
            description="uses", evidence_chunk_ids=("ev",),
        )
        local = fragment("f", "m", (
            element("root", "ev", semantic_key="local.root"),
            element("db", "ev", semantic_key="local.db"),
        ), (relation,))
        merged = merge_agent_graphs((local,), existing_references={"root": "analyst-system"})
        self.assertEqual(len(merged.relationships), 1)
        self.assertNotEqual(merged.relationships[0].source_id, "analyst-system")

    def test_parent_resolution_uses_required_c4_level_despite_alias_collision(self) -> None:
        infrastructure = AgentGraphFragment(
            fragment_id="infrastructure",
            metadata=AgentMetadata(agent_id="infra", role=AgentRole.INFRASTRUCTURE, model="fake"),
            elements=(element(
                "root", "ev", kind=ElementKind.CONTAINER, parent_ref="root",
            ),),
        )
        module = fragment("module", "module", (element("root", "ev", parent_ref="root"),))

        merged = merge_agent_graphs((infrastructure, module), existing_references={"root": "analyst-system"})

        container = next(item for item in merged.elements if item.kind == ElementKind.CONTAINER)
        component = next(item for item in merged.elements if item.kind == ElementKind.COMPONENT)
        self.assertEqual(container.parent_id, "analyst-system")
        self.assertEqual(component.parent_id, container.id)

    def test_self_relationship_is_quarantined(self) -> None:
        relation = FragmentRelationship(
            local_id="self", source_ref="api", target_ref="api", description="self", evidence_chunk_ids=("ev",),
        )
        merged = merge_agent_graphs((fragment("f", "m", (element("api", "ev"),), (relation,)),))
        self.assertEqual(merged.relationships, ())
        self.assertEqual(merged.orphans[0].reason, "Self relationship is not a valid C4 candidate")


class _ConcurrentAgent:
    def __init__(self, role: AgentRole, module_id: str | None, tracker, lock: threading.Lock, bad=False, query="architecture"):
        self.role = role
        self.module_id = module_id
        self.tracker = tracker
        self.lock = lock
        self.bad = bad
        self.query = query

    def _run(self, request, retrieve):
        self.assert_policy(request.prompt)
        with self.lock:
            self.tracker["active"] += 1
            self.tracker["maximum"] = max(self.tracker["maximum"], self.tracker["active"])
        try:
            chunks = retrieve(self.query, 100)
            time.sleep(0.01 if self.module_id != "slow" else 0.03)
            citation = "fabricated" if self.bad else chunks[0].id
            kind = ElementKind.CONTAINER if self.role == AgentRole.INFRASTRUCTURE else ElementKind.COMPONENT
            return AgentGraphFragment(
                fragment_id=self.module_id or "infrastructure",
                metadata=AgentMetadata(
                    agent_id=f"agent-{self.module_id or 'infra'}",
                    role=self.role,
                    module_id=self.module_id,
                    model="fake",
                ),
                elements=(element(
                    self.module_id or "infra",
                    citation,
                    kind=kind,
                    parent_ref="root",
                ),),
            )
        finally:
            with self.lock:
                self.tracker["active"] -= 1

    @staticmethod
    def assert_policy(prompt):
        if "untrusted" not in prompt or "authorized" not in prompt:
            raise AssertionError("security policy missing")

    def analyze_infrastructure(self, request, retrieve):
        return self._run(request, retrieve)

    def analyze_module(self, request, retrieve):
        return self._run(request, retrieve)


class OrchestrationTests(unittest.TestCase):
    def _orchestrator(self, *, bad_module=None, infrastructure_query="architecture"):
        tracker = {"active": 0, "maximum": 0, "largest_limit": 0, "queries": []}
        lock = threading.Lock()
        infra = _ConcurrentAgent(AgentRole.INFRASTRUCTURE, None, tracker, lock, query=infrastructure_query)

        def factory(module_id):
            return _ConcurrentAgent(AgentRole.MODULE, module_id, tracker, lock, bad=module_id == bad_module)

        def retriever(query, module_id, limit):
            tracker["largest_limit"] = max(tracker["largest_limit"], limit)
            tracker["queries"].append(query)
            return (RetrievalChunk(id=f"chunk-{module_id or 'infra'}", content="untrusted source"),)

        return AgentOrchestrator(infra, factory, retriever, max_concurrency=2, max_chunks_per_query=3), tracker

    def test_bounded_parallelism_and_deterministic_output_order(self) -> None:
        orchestrator, tracker = self._orchestrator()
        output = orchestrator.run(
            (ModuleWork(module_id="slow"), ModuleWork(module_id="a")),
            infrastructure_references=({
                "local_id": "root", "semantic_key": "root", "name": "Root", "kind": "software_system",
            },),
        )
        self.assertEqual(tuple(item.fragment_id for item in output), ("infrastructure", "a", "slow"))
        self.assertLessEqual(tracker["maximum"], 2)
        self.assertEqual(tracker["largest_limit"], 3)

    def test_normalizes_and_bounds_retrieval_queries(self) -> None:
        query = "dependencies   " + "  ".join(f"symbol-{index}" for index in range(100))
        orchestrator, tracker = self._orchestrator(infrastructure_query=query)
        orchestrator.run(
            (),
            infrastructure_references=({
                "local_id": "root", "semantic_key": "root", "name": "Root", "kind": "software_system",
            },),
        )
        bounded = tracker["queries"][0]
        self.assertEqual(len(bounded), 250)
        self.assertNotIn("  ", bounded)

    def test_rejects_citation_not_returned_by_retriever(self) -> None:
        orchestrator, _tracker = self._orchestrator(bad_module="bad")
        with self.assertRaisesRegex(AgentOrchestrationError, "unavailable chunks"):
            orchestrator.run(
                (ModuleWork(module_id="bad"),),
                infrastructure_references=({
                    "local_id": "root", "semantic_key": "root", "name": "Root", "kind": "software_system",
                },),
            )

    def test_wraps_heartbeat_transport_failure_in_agent_orchestration_error(self) -> None:
        orchestrator, _tracker = self._orchestrator()

        def failing_heartbeat(_done, _total, _label) -> None:
            raise httpx.RemoteProtocolError("Server disconnected")

        with self.assertRaisesRegex(AgentOrchestrationError, "progress heartbeat failed"):
            orchestrator.run(
                (ModuleWork(module_id="a"),),
                infrastructure_references=({
                    "local_id": "root", "semantic_key": "root", "name": "Root", "kind": "software_system",
                },),
                heartbeat=failing_heartbeat,
            )

    def test_spanish_database_is_not_offered_as_module_parent(self) -> None:
        infrastructure = Mock()
        infrastructure.analyze_infrastructure.return_value = AgentGraphFragment(
            fragment_id="infrastructure",
            metadata=AgentMetadata(agent_id="infra", role=AgentRole.INFRASTRUCTURE, model="fake"),
            elements=(
                element("app", "chunk-infra", kind=ElementKind.CONTAINER, parent_ref="root"),
                FragmentElement(
                    local_id="db",
                    kind=ElementKind.CONTAINER,
                    name="Base de datos PostgreSQL",
                    description="Almacén relacional de la aplicación",
                    technology="PostgreSQL",
                    parent_ref="root",
                    evidence_chunk_ids=("chunk-infra",),
                ),
            ),
        )
        module = Mock()

        def analyze(request, _retrieve):
            self.assertEqual([item["local_id"] for item in request.architecture_references], ["app"])
            return fragment("module", "module", (
                element("users", "chunk-module", semantic_key="users", parent_ref="app"),
            ))

        module.analyze_module.side_effect = analyze
        orchestrator = AgentOrchestrator(
            infrastructure,
            lambda _module_id: module,
            lambda _query, module_id, _limit: (
                RetrievalChunk(id=f"chunk-{module_id or 'infra'}", content="source"),
            ),
        )

        orchestrator.run(
            (ModuleWork(
                module_id="module",
                local_chunks=(RetrievalChunk(id="chunk-module", content="source"),),
            ),),
            infrastructure_chunks=(RetrievalChunk(id="chunk-infra", content="source"),),
            infrastructure_references=({
                "local_id": "root", "semantic_key": "root", "name": "Root", "kind": "software_system",
            },),
        )


class JudgeTests(unittest.TestCase):
    def test_judge_references_must_exist(self) -> None:
        graph = merge_agent_graphs((fragment("f", "module", (element("api", "ev", semantic_key="api"),)),))
        valid = JudgeReport(
            judge="fake",
            findings=(JudgeFinding(
                id="finding",
                severity=FindingSeverity.WARNING,
                code="review",
                message="Review boundary",
                element_ids=(graph.elements[0].id,),
                evidence_chunk_ids=("ev",),
            ),),
        )
        self.assertIs(validate_judge_report(valid, graph), valid)
        invalid = valid.model_copy(update={"findings": (
            valid.findings[0].model_copy(update={"element_ids": ("invented",)}),
        )})
        with self.assertRaisesRegex(ValueError, "unknown IDs"):
            validate_judge_report(invalid, graph)

    def test_deterministic_judge_detects_overlapping_capability_names(self) -> None:
        users = element("users", "ev-users", semantic_key="users")
        manager = element("manager", "ev-manager", semantic_key="manager")
        graph = merge_agent_graphs((fragment("f", "module", (users, manager)),))
        graph = graph.model_copy(update={
            "elements": (
                graph.elements[0].model_copy(update={"name": "Gestión de Usuarios", "parent_id": "api"}),
                graph.elements[1].model_copy(update={"name": "Gestor de Usuarios", "parent_id": "api"}),
            ),
        })

        report = deterministic_judge_report(graph)

        self.assertEqual(report.findings[0].code, "semantic_duplicate")


class GeminiSchemaTests(unittest.TestCase):
    def test_capability_key_removes_technical_layer_suffixes(self) -> None:
        self.assertEqual(canonical_capability_key("article-service"), "article")
        self.assertEqual(canonical_capability_key("article-repository"), "article")
        self.assertEqual(canonical_capability_key("article-creation"), "article")
        self.assertEqual(canonical_capability_key("user-authentication-service"), "user-authentication")
        self.assertEqual(canonical_capability_key("usuarios"), "user")
        self.assertEqual(canonical_capability_key("users"), "user")

    def test_fragment_sanitization_removes_invalid_and_duplicate_relationships(self) -> None:
        valid = FragmentRelationship(
            local_id="uses",
            source_ref="component",
            target_ref="container",
            description="Uses container",
            evidence_chunk_ids=("chunk",),
        )
        value = AgentGraphFragment(
            fragment_id="fragment",
            metadata=AgentMetadata(agent_id="agent", role=AgentRole.MODULE, module_id="app", model="test"),
            elements=(element("component", "chunk", parent_ref="container"),),
            relationships=(
                valid,
                valid,
                valid.model_copy(update={"local_id": "self", "target_ref": "component"}),
                valid.model_copy(update={"local_id": "alias", "source_ref": "ev1"}),
                valid.model_copy(update={"local_id": "missing", "target_ref": "unknown"}),
            ),
        )

        result = sanitize_agent_fragment(value, ({"local_id": "container", "semantic_key": "api"},))

        self.assertEqual(result.relationships, (valid,))

    def test_fragment_sanitization_allows_empty_module_after_removing_plumbing(self) -> None:
        value = AgentGraphFragment(
            fragment_id="core",
            metadata=AgentMetadata(agent_id="agent", role=AgentRole.MODULE, module_id="app/core", model="test"),
            elements=(
                element("logging", "chunk", parent_ref="container").model_copy(update={"name": "Logging Configuration"}),
                element("handler", "chunk", parent_ref="container").model_copy(update={"name": "User Update Handler"}),
            ),
        )

        result = sanitize_agent_fragment(value, ({"local_id": "container", "semantic_key": "api"},))

        self.assertEqual(result.elements, ())

    def test_local_context_selection_keeps_only_complete_chunks_in_order(self) -> None:
        chunks = (
            RetrievalChunk(id="first", content="a" * 20),
            RetrievalChunk(id="too-large", content="b" * 200),
            RetrievalChunk(id="last", content="c"),
        )
        first_size = len(json.dumps(chunks[0].model_dump(mode="json"), separators=(",", ":")))
        last_size = len(json.dumps(chunks[2].model_dump(mode="json"), separators=(",", ":")))
        selected = select_whole_chunks(chunks, first_size + last_size)
        self.assertEqual(tuple(item.id for item in selected), ("first", "last"))
        with self.assertRaisesRegex(RuntimeError, "No complete evidence chunk"):
            select_whole_chunks(chunks, 1)

    def test_gemini_transient_errors_are_retried_with_bounded_backoff(self) -> None:
        attempts = []
        delays = []

        def generate():
            attempts.append(True)
            if len(attempts) < 3:
                raise _GeminiError(503)
            return "response"

        self.assertEqual(generate_with_retry(generate, delays.append), "response")
        self.assertEqual(len(attempts), 3)
        self.assertEqual(delays, [15.0, 30.0])

    def test_gemini_non_transient_errors_are_not_retried(self) -> None:
        attempts = []

        def generate():
            attempts.append(True)
            raise _GeminiError(400)

        with self.assertRaises(_GeminiError):
            generate_with_retry(generate, lambda _delay: None)
        self.assertEqual(len(attempts), 1)

    def test_gemini_daily_quota_exhaustion_is_not_retried(self) -> None:
        attempts = []

        def generate():
            attempts.append(True)
            raise _GeminiError(429, {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"})

        with self.assertRaises(_GeminiError):
            generate_with_retry(generate, lambda _delay: None)
        self.assertEqual(len(attempts), 1)

    def test_evidence_aliases_are_stable_and_restored_before_validation(self) -> None:
        alias_by_id, id_by_alias = evidence_aliases({"chunk-z", "chunk-a"})
        self.assertEqual(alias_by_id, {"chunk-a": "ev0", "chunk-z": "ev1"})
        restored = restore_evidence_aliases(
            {"elements": [{"evidence_chunk_ids": ["ev1"]}]},
            id_by_alias,
        )
        self.assertEqual(restored["elements"][0]["evidence_chunk_ids"], ["chunk-z"])
        with self.assertRaisesRegex(ValueError, "unknown evidence aliases"):
            restore_evidence_aliases({"evidence_chunk_ids": ["invented"]}, id_by_alias)

    def test_agent_response_schema_constrains_every_evidence_citation(self) -> None:
        allowed = {"chunk-local", "chunk-retrieved"}
        schema = agent_response_schema(
            AgentRole.INFRASTRUCTURE,
            allowed,
            ("system-root",),
            "infrastructure",
        )
        references = []

        def collect(value):
            if isinstance(value, dict):
                properties = value.get("properties")
                if isinstance(properties, dict) and "evidence_chunk_ids" in properties:
                    references.append(properties["evidence_chunk_ids"]["items"])
                for item in value.values():
                    collect(item)
            elif isinstance(value, list):
                for item in value:
                    collect(item)

        collect(schema)
        self.assertEqual(
            schema["$defs"]["AllowedEvidenceChunkId"],
            {"type": "string", "enum": sorted(allowed)},
        )
        self.assertEqual(len(references), 3)
        self.assertTrue(all(item == {"$ref": "#/$defs/AllowedEvidenceChunkId"} for item in references))
        self.assertNotIn("evidence-invented", schema["$defs"]["AllowedEvidenceChunkId"]["enum"])
        self.assertEqual(
            schema["properties"]["fragment_id"],
            {"type": "string", "enum": ["infrastructure"]},
        )
        infrastructure_element = schema["$defs"]["_InfrastructureElement"]
        self.assertEqual(
            infrastructure_element["properties"]["parent_ref"],
            {"type": "string", "enum": ["system-root"]},
        )
        self.assertIn("parent_ref", infrastructure_element["required"])
        self.assertEqual(schema["properties"]["elements"]["maxItems"], 2)
        module_schema = agent_response_schema(AgentRole.MODULE, allowed, ("api",), "orders")
        self.assertEqual(module_schema["properties"]["elements"]["minItems"], 0)
        self.assertIn("semantic_key", module_schema["$defs"]["_ModuleElement"]["required"])
        self.assertEqual(schema["properties"]["elements"]["minItems"], 1)
        with self.assertRaisesRegex(ValueError, "at least one evidence"):
            agent_response_schema(AgentRole.MODULE, set())

    def test_retrieval_queries_are_deterministic_and_bounded(self) -> None:
        infrastructure = deterministic_retrieval_queries(AgentRole.INFRASTRUCTURE, None)
        module = deterministic_retrieval_queries(AgentRole.MODULE, "orders/api")
        self.assertEqual(len(infrastructure), 2)
        self.assertEqual(len(module), 2)
        self.assertIn("orders/api", module[0])
        self.assertTrue(all(0 < len(query) <= 250 for query in (*infrastructure, *module)))

    def test_agent_response_models_restrict_element_kind_by_role(self) -> None:
        cases = (
            (AgentRole.INFRASTRUCTURE, ElementKind.CONTAINER, ElementKind.SOFTWARE_SYSTEM),
            (AgentRole.MODULE, ElementKind.COMPONENT, ElementKind.CONTAINER),
        )
        for role, allowed, rejected in cases:
            with self.subTest(role=role):
                payload = AgentGraphFragment(
                    fragment_id="fragment",
                    metadata=AgentMetadata(
                        agent_id="agent", role=role, module_id=None if role == AgentRole.INFRASTRUCTURE else "module", model="fake",
                    ),
                    elements=(element("item", "evidence", kind=allowed, parent_ref="root"),),
                ).model_dump(mode="json")
                if role == AgentRole.MODULE:
                    payload["elements"][0]["semantic_key"] = "orders"
                response_model = agent_response_model(role)
                response_model.model_validate_json(json.dumps(payload))
                payload["elements"][0]["kind"] = rejected.value
                with self.assertRaises(ValidationError):
                    response_model.model_validate_json(json.dumps(payload))

    def test_schema_removes_unsupported_additional_properties_recursively(self) -> None:
        schema = gemini_json_schema(AgentGraphFragment)

        def keys(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    yield key
                    yield from keys(item)
            elif isinstance(value, list):
                for item in value:
                    yield from keys(item)

        self.assertNotIn("additionalProperties", set(keys(schema)))
        self.assertIn("$defs", schema)

    def test_local_agent_validation_still_forbids_extra_fields(self) -> None:
        valid = fragment("f", "module", (element("api", "ev"),)).model_dump(mode="json")
        valid["unexpected"] = True
        with self.assertRaises(ValidationError):
            AgentGraphFragment.model_validate(valid)


class CapabilityConsolidationTests(unittest.TestCase):
    def _element(self, item_id, name, module):
        return MergedElement(
            id=item_id,
            identity=item_id,
            kind=ElementKind.COMPONENT,
            name=name,
            description=f"Responsabilidad arquitectónica de {name}",
            parent_id="api",
            evidence_chunk_ids=(f"ev-{item_id}",),
            agent_ids=(module,),
            module_ids=(module,),
            models=("qwen3:8b",),
        )

    def _graph(self):
        container = MergedElement(
            id="api",
            identity="api",
            kind=ElementKind.CONTAINER,
            name="API",
            description="Aplicación HTTP",
            parent_id="system",
            evidence_chunk_ids=("ev-api",),
            agent_ids=("infra",),
            module_ids=(),
            models=("qwen3:8b",),
        )
        article_api = self._element("article-api", "Article Management Module", "app/api")
        article_repository = self._element("article-repository", "Artículo Repositorio", "app/db")
        authentication = self._element("authentication", "Gestión de Autenticación", "app/services")
        relationships = (
            MergedRelationship(
                id="internal",
                source_id="article-api",
                target_id="article-repository",
                description="usa",
                technology="Python import",
                evidence_chunk_ids=("ev-internal",),
            ),
            MergedRelationship(
                id="auth",
                source_id="article-api",
                target_id="authentication",
                description="valida usuario",
                technology="Python import",
                evidence_chunk_ids=("ev-auth",),
            ),
        )
        return MergedAgentGraph(
            elements=(container, article_api, article_repository, authentication),
            relationships=relationships,
        )

    def test_high_confidence_group_merges_evidence_and_rewrites_relationships(self):
        plan = CapabilityConsolidationPlan(groups=(CapabilityGroup(
            capability_key="articles",
            canonical_name="Gestión de Artículos",
            canonical_description="Gestiona el ciclo de vida de los artículos",
            member_ids=("article-api", "article-repository"),
            confidence="high",
            reason="Misma capacidad representada en API y persistencia",
        ),))

        result = apply_consolidation_plan(self._graph(), plan)

        article = next(item for item in result.elements if item.identity == "capability:articles")
        self.assertEqual(set(article.evidence_chunk_ids), {"ev-article-api", "ev-article-repository"})
        self.assertEqual(set(article.module_ids), {"app/api", "app/db"})
        self.assertEqual(len(result.relationships), 1)
        self.assertEqual(result.relationships[0].source_id, article.id)
        self.assertEqual(result.relationships[0].target_id, "authentication")

    def test_uncertain_group_is_preserved_as_semantic_conflict(self):
        plan = CapabilityConsolidationPlan(groups=(CapabilityGroup(
            capability_key="identity",
            canonical_name="Identidad",
            canonical_description="Posible capacidad compartida de identidad",
            member_ids=("article-api", "authentication"),
            confidence="uncertain",
            reason="Las responsabilidades se relacionan pero no son equivalentes",
        ),))

        result = apply_consolidation_plan(self._graph(), plan)

        self.assertEqual(len(result.elements), 4)
        self.assertEqual(result.conflicts[0].kind.value, "semantic")

    def test_overlapping_groups_are_discarded_before_application(self):
        plan = CapabilityConsolidationPlan(groups=(
            CapabilityGroup(
                capability_key="articles",
                canonical_name="Artículos",
                canonical_description="Posible capacidad de artículos",
                member_ids=("article-api", "authentication"),
                confidence="uncertain",
                reason="Posible responsabilidad compartida entre candidatos",
            ),
            CapabilityGroup(
                capability_key="identity",
                canonical_name="Identidad",
                canonical_description="Posible capacidad de identidad",
                member_ids=("article-repository", "authentication"),
                confidence="uncertain",
                reason="Posible responsabilidad compartida entre candidatos",
            ),
        ))

        sanitized = sanitize_consolidation_plan(plan)

        self.assertEqual(sanitized.groups, ())

    def test_semantically_unrelated_group_is_discarded(self):
        plan = CapabilityConsolidationPlan(groups=(CapabilityGroup(
            capability_key="article-management",
            canonical_name="Gestión editorial",
            canonical_description="Posible capacidad editorial compartida",
            member_ids=("article-api", "authentication"),
            confidence="uncertain",
            reason="Las capacidades están relacionadas, pero no son idénticas",
        ),))

        sanitized = sanitize_consolidation_plan(plan, self._graph())

        self.assertEqual(sanitized.groups, ())

    def test_overlapping_capability_names_can_be_repaired(self):
        users = self._element("users", "Gestión de Usuarios", "app/api")
        manager = self._element("user-manager", "Gestor de Usuarios", "app/services")
        graph = MergedAgentGraph(elements=(users, manager), relationships=())
        plan = CapabilityConsolidationPlan(groups=(CapabilityGroup(
            capability_key="users",
            canonical_name="Gestión de Usuarios",
            canonical_description="Gestiona el ciclo de vida completo de los usuarios",
            member_ids=(users.id, manager.id),
            confidence="high",
            reason="Representan la misma capacidad en capas diferentes",
        ),))

        sanitized = sanitize_consolidation_plan(plan, graph)
        repaired = apply_consolidation_plan(graph, sanitized)

        self.assertEqual(len(sanitized.groups), 1)
        self.assertEqual(len(repaired.elements), 1)
        self.assertEqual(set(repaired.elements[0].evidence_chunk_ids), {"ev-users", "ev-user-manager"})


class OllamaAgentTests(unittest.TestCase):
    @patch("agentic_c4.ollama.httpx.post")
    def test_ollama_uses_schema_and_restores_canonical_evidence_ids(self, post) -> None:
        response = Mock()
        response.json.return_value = {
            "message": {
                "content": json.dumps({
                    "fragment_id": "infrastructure",
                    "metadata": {
                        "agent_id": "ollama-infrastructure-root",
                        "role": "infrastructure",
                        "module_id": None,
                        "model": "qwen3:8b",
                    },
                    "elements": [{
                        "local_id": "api",
                        "kind": "container",
                        "name": "API",
                        "description": "Application HTTP API",
                        "parent_ref": "root",
                        "evidence_chunk_ids": ["ev0"],
                    }],
                    "relationships": [],
                    "unresolved_references": [],
                })
            }
        }
        post.return_value = response
        request = AgentRequest(
            role=AgentRole.INFRASTRUCTURE,
            prompt="authorized untrusted policy",
            local_chunks=(RetrievalChunk(id="chunk-local", content="source"),),
            architecture_references=({
                "local_id": "root", "semantic_key": "root", "name": "Root", "kind": "software_system",
            },),
        )

        result = OllamaC4Agent(AgentRole.INFRASTRUCTURE, model="qwen3:8b").analyze_infrastructure(
            request, lambda _query, _limit: ()
        )

        self.assertEqual(result.elements[0].evidence_chunk_ids, ("chunk-local",))
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["model"], "qwen3:8b")
        self.assertFalse(body["think"])
        self.assertEqual(body["format"]["$defs"]["AllowedEvidenceChunkId"]["enum"], ["ev0"])
        response.raise_for_status.assert_called_once_with()

    @patch("agentic_c4.ollama.httpx.post")
    def test_ollama_retries_locally_invalid_structured_output(self, post) -> None:
        def response(description):
            value = Mock()
            value.json.return_value = {"message": {"content": json.dumps({
                "fragment_id": "infrastructure",
                "metadata": {
                    "agent_id": "ollama-infrastructure-root",
                    "role": "infrastructure",
                    "module_id": None,
                    "model": "qwen3:8b",
                },
                "elements": [{
                    "local_id": "api",
                    "kind": "container",
                    "name": "API",
                    "description": description,
                    "parent_ref": "root",
                    "evidence_chunk_ids": ["ev0"],
                }],
                "relationships": [],
                "unresolved_references": [],
            })}}
            return value

        post.side_effect = [response(""), response("Application HTTP API")]
        request = AgentRequest(
            role=AgentRole.INFRASTRUCTURE,
            prompt="authorized untrusted policy",
            local_chunks=(RetrievalChunk(id="chunk-local", content="source"),),
            architecture_references=({
                "local_id": "root", "semantic_key": "root", "name": "Root", "kind": "software_system",
            },),
        )

        result = OllamaC4Agent(AgentRole.INFRASTRUCTURE, model="qwen3:8b").analyze_infrastructure(
            request, lambda _query, _limit: ()
        )

        self.assertEqual(result.elements[0].description, "Application HTTP API")
        self.assertEqual(post.call_count, 2)
        self.assertIn("Fix these validation errors", post.call_args.kwargs["json"]["messages"][1]["content"])

    @patch("agentic_c4.ollama.httpx.post")
    def test_ollama_retries_duplicate_element_ids(self, post) -> None:
        def response(local_ids):
            value = Mock()
            value.json.return_value = {"message": {"content": json.dumps({
                "fragment_id": "infrastructure",
                "metadata": {
                    "agent_id": "ollama-infrastructure-root",
                    "role": "infrastructure",
                    "module_id": None,
                    "model": "qwen3:8b",
                },
                "elements": [{
                    "local_id": local_id,
                    "kind": "container",
                    "name": f"API {index}",
                    "description": f"Application HTTP API number {index}",
                    "parent_ref": "root",
                    "evidence_chunk_ids": ["ev0"],
                } for index, local_id in enumerate(local_ids, start=1)],
                "relationships": [],
                "unresolved_references": [],
            })}}
            return value

        post.side_effect = [response(("container_1", "container_1")), response(("container_1", "container_2"))]
        request = AgentRequest(
            role=AgentRole.INFRASTRUCTURE,
            prompt="authorized untrusted policy",
            local_chunks=(RetrievalChunk(id="chunk-local", content="source"),),
            architecture_references=({
                "local_id": "root", "semantic_key": "root", "name": "Root", "kind": "software_system",
            },),
        )

        result = OllamaC4Agent(AgentRole.INFRASTRUCTURE, model="qwen3:8b").analyze_infrastructure(
            request, lambda _query, _limit: ()
        )

        self.assertEqual([item.local_id for item in result.elements], ["container_1", "container_2"])
        self.assertEqual(post.call_count, 2)
        correction = post.call_args.kwargs["json"]["messages"][1]["content"]
        self.assertIn("local_id must be unique", correction)

    @patch("agentic_c4.ollama.httpx.post")
    def test_ollama_retries_transient_transport_error(self, post) -> None:
        response = Mock()
        response.json.return_value = {"message": {"content": json.dumps({
            "fragment_id": "infrastructure",
            "metadata": {
                "agent_id": "ollama-infrastructure-root",
                "role": "infrastructure",
                "module_id": None,
                "model": "qwen3:8b",
            },
            "elements": [{
                "local_id": "api",
                "kind": "container",
                "name": "API",
                "description": "Application HTTP API",
                "parent_ref": "root",
                "evidence_chunk_ids": ["ev0"],
            }],
            "relationships": [],
            "unresolved_references": [],
        })}}
        post.side_effect = [httpx.RemoteProtocolError("Server disconnected"), response]
        request = AgentRequest(
            role=AgentRole.INFRASTRUCTURE,
            prompt="authorized untrusted policy",
            local_chunks=(RetrievalChunk(id="chunk-local", content="source"),),
            architecture_references=({
                "local_id": "root", "semantic_key": "root", "name": "Root", "kind": "software_system",
            },),
        )

        result = OllamaC4Agent(AgentRole.INFRASTRUCTURE, model="qwen3:8b").analyze_infrastructure(
            request, lambda _query, _limit: ()
        )

        self.assertEqual(result.elements[0].name, "API")
        self.assertEqual(post.call_count, 2)
        self.assertEqual(len(post.call_args.kwargs["json"]["messages"]), 1)

    @patch("agentic_c4.ollama.httpx.post")
    def test_ollama_repairs_short_descriptions_after_retries_exhausted(self, post) -> None:
        def response():
            value = Mock()
            value.json.return_value = {"message": {"content": json.dumps({
                "fragment_id": "infrastructure",
                "metadata": {
                    "agent_id": "ollama-infrastructure-root",
                    "role": "infrastructure",
                    "module_id": None,
                    "model": "qwen3:8b",
                },
                "elements": [{
                    "local_id": "api",
                    "kind": "container",
                    "name": "API",
                    "description": "API",
                    "parent_ref": "root",
                    "evidence_chunk_ids": ["ev0"],
                }],
                "relationships": [],
                "unresolved_references": [],
            })}}
            return value

        post.side_effect = [response(), response()]
        request = AgentRequest(
            role=AgentRole.INFRASTRUCTURE,
            prompt="authorized untrusted policy",
            local_chunks=(RetrievalChunk(id="chunk-local", content="source"),),
            architecture_references=({
                "local_id": "root", "semantic_key": "root", "name": "Root", "kind": "software_system",
            },),
        )

        result = OllamaC4Agent(AgentRole.INFRASTRUCTURE, model="qwen3:8b").analyze_infrastructure(
            request, lambda _query, _limit: ()
        )

        self.assertEqual(post.call_count, 2)
        self.assertGreaterEqual(len(result.elements[0].description.strip()), 8)
        self.assertEqual(result.elements[0].local_id, "api")


if __name__ == "__main__":
    unittest.main()
