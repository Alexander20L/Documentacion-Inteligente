import json
import tempfile
import unittest
from pathlib import Path

from agentic_c4 import (
    AgentGraphFragment,
    AgentMetadata,
    AgentRole,
    CapabilityConsolidationPlan,
    CapabilityGroup,
    deterministic_judge_report,
    FragmentElement,
    MergedAgentGraph,
    MergedElement,
    MergedRelationship,
)
from c4core import AnalystContext, ElementKind, EvidenceSource, FilesystemExtractionAdapter, normalize_graphify_json
from semantic_rag import InMemoryKnowledgeIndex, PythonSemanticParser
from semantic_rag.models import Language, PublicationPolicy, SemanticChunk, SymbolKind, SymbolRecord, Visibility, ImportRecord
from servicios.c4_revision import candidatos_detectados_contexto, relaciones_detectadas_contexto
from servicios.c4_revision import crear_contenido_revision, revision_publica
from servicios.semantic_agent_pipeline import (
    _build_module_work,
    _augment_architecture_graph,
    _chunk_coherente_con_componente,
    _hit_in_agent_scope,
    _normalized_component_name,
    _path_matches_import,
    _reconcile_semantic_components,
    _reconcile_semantic_relationships,
    _validate_architecture_quality,
    _validate_gemini_request_budget,
    run_semantic_agent_pipeline,
    sanitize_semantic_work_copy,
)


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, database, table):
        self.database = database
        self.table = table
        self.operation = None
        self.payload = None
        self.row_id = None

    def insert(self, payload):
        self.operation, self.payload = "insert", dict(payload)
        return self

    def update(self, payload):
        self.operation, self.payload = "update", dict(payload)
        return self

    def delete(self):
        self.operation = "delete"
        return self

    def eq(self, column, value):
        if column == "id":
            self.row_id = value
        return self

    def execute(self):
        rows = self.database.rows.setdefault(self.table, [])
        if self.operation == "insert":
            row = {"id": f"{self.table}-{len(rows) + 1}", **self.payload}
            rows.append(row)
            return _Result([row])
        if self.operation == "update":
            row = next(item for item in rows if item["id"] == self.row_id)
            row.update(self.payload)
            return _Result([row])
        if self.operation == "delete":
            self.database.rows[self.table] = []
            return _Result([])
        raise AssertionError("unsupported fake query")


class _Database:
    def __init__(self):
        self.rows = {}

    def table(self, name):
        return _Query(self, name)


class _InfrastructureAgent:
    def __init__(self, root_id):
        self.root_id = root_id

    def analyze_infrastructure(self, request, retrieve):
        if not any(
            item.get("local_id") == self.root_id and item.get("kind") == ElementKind.SOFTWARE_SYSTEM.value
            for item in request.architecture_references
        ):
            raise AssertionError("analyst software system reference was not supplied")
        retrieved = retrieve("api", 2)
        citation = retrieved[0].id if retrieved else request.local_chunks[0].id
        return AgentGraphFragment(
            fragment_id="infrastructure",
            metadata=AgentMetadata(agent_id="fake-infra", role=AgentRole.INFRASTRUCTURE, model="fake"),
            elements=(FragmentElement(
                local_id="api-container",
                semantic_key="api-container",
                kind=ElementKind.CONTAINER,
                name="API",
                description="Application API container",
                parent_ref=self.root_id,
                evidence_chunk_ids=(citation,),
            ),),
        )


class _ModuleAgent:
    def __init__(self, module_id):
        self.module_id = module_id

    def analyze_module(self, request, retrieve):
        retrieved = retrieve("api", 2)
        citation = retrieved[0].id if retrieved else request.local_chunks[0].id
        is_api = self.module_id.endswith("/api")
        local_id = "order-api" if is_api else "order-processing"
        return AgentGraphFragment(
            fragment_id=f"module-{self.module_id}",
            metadata=AgentMetadata(
                agent_id=f"fake-{self.module_id}", role=AgentRole.MODULE, module_id=self.module_id, model="fake"
            ),
            elements=(FragmentElement(
                local_id=local_id,
                semantic_key=f"{self.module_id}.{local_id}",
                kind=ElementKind.COMPONENT,
                name="API de pedidos" if is_api else "Procesamiento de pedidos",
                description="Expone operaciones de pedidos" if is_api else "Gestiona las reglas de negocio de pedidos",
                parent_ref="api-container",
                evidence_chunk_ids=(citation,),
            ),),
        )


class _CapabilityConsolidator:
    model = "fake-consolidator"

    def __init__(self):
        self.calls = 0

    def consolidate(self, graph):
        self.calls += 1
        self.graph = graph
        components = tuple(item for item in graph.elements if item.kind == ElementKind.COMPONENT)
        if len(components) < 2:
            return CapabilityConsolidationPlan()
        return CapabilityConsolidationPlan(groups=(CapabilityGroup(
            capability_key="orders",
            canonical_name="Gestión de Pedidos",
            canonical_description="Gestiona el ciclo de vida completo de los pedidos",
            member_ids=tuple(item.id for item in components),
            confidence="high",
            reason="Representan la misma capacidad en capas diferentes",
        ),))


class SemanticAgentPipelineTests(unittest.TestCase):
    @staticmethod
    def _merged_element(item_id, name, kind, parent_id, evidence="ev", technology=None):
        return MergedElement(
            id=item_id,
            identity=item_id,
            kind=kind,
            name=name,
            description=f"Responsabilidad arquitectónica de {name}",
            technology=technology,
            parent_id=parent_id,
            evidence_chunk_ids=(evidence,),
            agent_ids=(item_id,),
            module_ids=(),
            models=("fake",),
        )

    def test_semantic_component_reconciliation_merges_plural_and_suffix_aliases(self):
        common = {
            "kind": ElementKind.COMPONENT,
            "parent_id": "api",
            "technology": None,
            "provenance": "inferred",
        }
        first = MergedElement(
            id="articles-db", identity="db", name="Articles Management Component",
            description="Gestiona artículos", evidence_chunk_ids=("ev-db",), agent_ids=("db",),
            module_ids=("app/db",), models=("model",), **common,
        )
        second = MergedElement(
            id="article-model", identity="model", name="Article Management Service",
            description="Gestiona la publicación de artículos", evidence_chunk_ids=("ev-model",), agent_ids=("model",),
            module_ids=("app/models",), models=("model",), **common,
        )

        reconciled = _reconcile_semantic_components([first, second])

        self.assertEqual(_normalized_component_name(first.name), "article")
        self.assertEqual(_normalized_component_name("Artículo Repositorio"), "article")
        self.assertEqual(_normalized_component_name("Gestión de Artículos"), "article")
        self.assertEqual(_normalized_component_name("Servicio de Creación de Artículos"), "article")
        self.assertEqual(_normalized_component_name("Adaptador del Repositorio de Artículos"), "article")
        self.assertEqual(_normalized_component_name("User Management Module"), "user")
        self.assertEqual(_normalized_component_name("Usuario Repositorio"), "user")
        self.assertEqual(len(reconciled), 1)
        self.assertEqual(set(reconciled[0].evidence_chunk_ids), {"ev-db", "ev-model"})

    def test_reconciliation_uses_multilingual_semantic_identities(self):
        users = self._merged_element("users", "Gestor de Usuarios", ElementKind.COMPONENT, "api", "ev-users")
        users = users.model_copy(update={"identity": "semantic:users"})
        usuarios = self._merged_element(
            "usuarios", "Gestión de Usuarios", ElementKind.COMPONENT, "api", "ev-usuarios"
        )
        usuarios = usuarios.model_copy(update={"identity": "semantic:usuarios"})

        reconciled = _reconcile_semantic_components([users, usuarios])

        self.assertEqual(len(reconciled), 1)
        self.assertEqual(set(reconciled[0].evidence_chunk_ids), {"ev-users", "ev-usuarios"})

    def test_quality_gate_preserves_component_cycles_for_advisory_review(self):
        container = MergedElement(
            id="api", identity="api", kind=ElementKind.CONTAINER, name="API", description="Aplicación",
            parent_id="system", evidence_chunk_ids=("ev",), agent_ids=("infra",), module_ids=(), models=("model",),
        )
        components = tuple(MergedElement(
            id=item, identity=item, kind=ElementKind.COMPONENT, name=name, description=name,
            parent_id="api", evidence_chunk_ids=(f"ev-{item}",), agent_ids=(item,), module_ids=(item,), models=("model",),
        ) for item, name in (("orders", "Pedidos"), ("billing", "Facturación")))
        relationships = (
            MergedRelationship(id="a", source_id="orders", target_id="billing", description="usa", technology="Python import", evidence_chunk_ids=("ev-a",)),
            MergedRelationship(id="b", source_id="billing", target_id="orders", description="usa", technology="Python import", evidence_chunk_ids=("ev-b",)),
        )
        graph = MergedAgentGraph(elements=(container, *components), relationships=relationships)

        _validate_architecture_quality(graph)

        report = deterministic_judge_report(graph)
        self.assertEqual(report.findings[0].code, "component_cycle")
        self.assertEqual(report.findings[0].severity.value, "warning")

    def test_reconciliation_removes_spanish_plumbing_and_container_duplicates(self):
        container = MergedElement(
            id="api", identity="api", kind=ElementKind.CONTAINER, name="FastAPI Application", description="API",
            parent_id="system", evidence_chunk_ids=("ev-api",), agent_ids=("infra",), module_ids=(), models=("model",),
        )
        names = (
            ("logs", "Manejo de Registros", "Configura Loguru y el sistema de registro", "app/core"),
            ("routes", "Gestión de Rutas y Endpoints", "Organiza las rutas HTTP", "app"),
            ("server", "Servidor de Aplicación FastAPI", "Configura middleware", "app"),
            ("articles", "Gestión de Artículos", "Gestiona artículos", "app/services"),
        )
        components = [MergedElement(
            id=item_id, identity=item_id, kind=ElementKind.COMPONENT, name=name, description=description,
            parent_id="api", evidence_chunk_ids=(f"ev-{item_id}",), agent_ids=(item_id,), module_ids=(module,), models=("model",),
        ) for item_id, name, description, module in names]

        reconciled = _reconcile_semantic_components([container, *components])

        self.assertEqual([(item.kind.value, item.name) for item in reconciled], [
            ("container", "FastAPI Application"),
            ("component", "Gestión de Artículos"),
        ])

    def test_augmentation_canonicalizes_spanish_postgresql_and_repairs_component_parent(self):
        parser = PythonSemanticParser()
        chunk = parser.parse(
            "from pydantic import PostgresDsn\n\ndef configure_database():\n    return PostgresDsn\n",
            "repo/app/config.py",
            tenant_id="tenant",
            repository_id="repository",
        )[0]
        server = self._merged_element("api", "Servidor de Aplicación FastAPI", ElementKind.CONTAINER, "system", chunk.id)
        database = self._merged_element(
            "db-es", "Base de Datos PostgreSQL", ElementKind.CONTAINER, "system", chunk.id, "PostgreSQL"
        )
        user_in_database = self._merged_element(
            "users-db", "Gestión de Usuarios", ElementKind.COMPONENT, database.id, chunk.id
        )
        user_in_server = self._merged_element(
            "users-api", "Gestión de Usuarios", ElementKind.COMPONENT, server.id, chunk.id
        )

        result = _augment_architecture_graph(
            MergedAgentGraph(elements=(server, database, user_in_database, user_in_server), relationships=()),
            (chunk,),
            (),
            "system",
            "RealWorld",
        )

        containers = [item for item in result.elements if item.kind == ElementKind.CONTAINER]
        components = [item for item in result.elements if item.kind == ElementKind.COMPONENT]
        self.assertEqual([item.name for item in containers], ["Servidor de Aplicación FastAPI", "Base de datos PostgreSQL"])
        self.assertEqual(len(components), 1)
        self.assertEqual(components[0].parent_id, server.id)
        self.assertEqual(len(result.relationships), 1)
        self.assertEqual(result.relationships[0].target_id, containers[1].id)

    def test_relationship_reconciliation_removes_semantic_self_edges_and_duplicates(self):
        comment = self._merged_element("comments", "Gestión de Comentarios", ElementKind.COMPONENT, "api")
        user_a = self._merged_element("users-a", "Gestión de Usuarios", ElementKind.COMPONENT, "api")
        user_b = self._merged_element("users-b", "Gestión de Usuarios", ElementKind.COMPONENT, "db")
        relationships = [
            MergedRelationship(
                id="self", source_id=user_a.id, target_id=user_b.id, description="depende", technology="Python import",
                evidence_chunk_ids=("ev-self",),
            ),
            MergedRelationship(
                id="a", source_id=comment.id, target_id=user_a.id, description="depende", technology="Python import",
                evidence_chunk_ids=("ev-a",),
            ),
            MergedRelationship(
                id="b", source_id=comment.id, target_id=user_b.id, description="depende", technology="Python import",
                evidence_chunk_ids=("ev-b",),
            ),
        ]

        reconciled = _reconcile_semantic_relationships([comment, user_a, user_b], relationships)

        self.assertEqual(len(reconciled), 1)
        self.assertEqual(set(reconciled[0].evidence_chunk_ids), {"ev-a", "ev-b"})

    def test_analyst_relationship_description_is_spanish(self):
        elements, system_id = candidatos_detectados_contexto({
            "nombre_sistema": "Orders",
            "descripcion": "",
            "proposito": "",
            "actores": [{"nombre": "Operador", "descripcion": ""}],
            "sistemas_externos": [],
        }, "evidence")

        relationship = relaciones_detectadas_contexto(elements, system_id, "evidence")[0]

        self.assertEqual(relationship.description, "Operador utiliza el sistema de software")

    def test_retrieval_scope_excludes_tests_and_other_modules(self):
        self.assertTrue(_hit_in_agent_scope("repo/app/models/users.py", "repo/app/models"))
        self.assertFalse(_hit_in_agent_scope("repo/app/db/users.py", "repo/app/models"))
        self.assertFalse(_hit_in_agent_scope("repo/tests/test_users.py", "repo/app/models"))
        self.assertFalse(_hit_in_agent_scope("repo/tests/test_users.py", None))

    def test_gemini_budget_counts_infrastructure_modules_and_optional_judge(self):
        self.assertEqual(_validate_gemini_request_budget(6, judge_enabled=False, max_requests=20), 8)
        self.assertEqual(_validate_gemini_request_budget(6, judge_enabled=True, max_requests=20), 9)
        with self.assertRaisesRegex(RuntimeError, "requiere 22 solicitudes"):
            _validate_gemini_request_budget(19, judge_enabled=True, max_requests=20)

    def test_module_work_groups_architectural_areas_and_bounds_agent_count(self):
        parser = PythonSemanticParser()
        paths = (
            "repo/app/main.py",
            "repo/app/api/routes/articles.py",
            "repo/app/api/dependencies/auth.py",
            "repo/app/core/settings.py",
            "repo/app/db/repositories/users.py",
            "repo/app/models/domain/users.py",
            "repo/app/services/articles.py",
            "repo/tests/test_api/test_routes.py",
        )
        chunks = tuple(
            parser.parse(
                f"def item_{index}():\n    return {index}\n",
                path,
                tenant_id="tenant",
                repository_id="repository",
            )[0]
            for index, path in enumerate(paths)
        )

        modules = _build_module_work(chunks, 8)

        self.assertEqual(
            {module.module_id for module in modules},
            {"repo/app", "repo/app/api", "repo/app/core", "repo/app/db", "repo/app/models", "repo/app/services"},
        )
        self.assertEqual(sum(len(module.local_chunks) for module in modules), len(chunks) - 1)
        bounded = _build_module_work(chunks, 3)
        self.assertEqual(len(bounded), 3)
        self.assertEqual(sum(len(module.local_chunks) for module in bounded), len(chunks) - 1)

    def test_review_hash_includes_semantic_metadata(self):
        element = candidatos_detectados_contexto({
            "nombre_sistema": "Orders", "descripcion": "", "proposito": "", "actores": [], "sistemas_externos": []
        }, "evidence")[0]
        first = revision_publica(crear_contenido_revision(element, (), metadata={"conflictos": [{"id": "one"}]}))
        second = revision_publica(crear_contenido_revision(element, (), metadata={"conflictos": [{"id": "two"}]}))
        self.assertNotEqual(first["hash"], second["hash"])
        self.assertEqual(first["conflictos"], [{"id": "one"}])

    def test_in_memory_pipeline_removes_denied_files_and_persists_hash_only_audits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work = root / "work"
            run = root / "run"
            (work / "app" / "api").mkdir(parents=True)
            (work / "app" / "services").mkdir(parents=True)
            (work / "app" / "api" / "routes.py").write_text(
                "from app.services.orders import list_orders\n\ndef api():\n    return list_orders()\n",
                encoding="utf-8",
            )
            (work / "app" / "services" / "orders.py").write_text(
                "def list_orders():\n    return 'orders'\n",
                encoding="utf-8",
            )
            (work / "secrets.py").write_text("def leaked():\n    return 'do-not-store'\n", encoding="utf-8")
            preliminary_scans = sanitize_semantic_work_copy(work)
            analyst = AnalystContext(repository_name="repo", system_name="Orders")
            extraction = FilesystemExtractionAdapter().extract(work, analyst)
            analyst_evidence = next(item for item in extraction.evidence if item.source == EvidenceSource.ANALYST)
            detected, system_id = candidatos_detectados_contexto({
                "nombre_sistema": "Orders", "descripcion": "", "proposito": "", "actores": [], "sistemas_externos": []
            }, analyst_evidence.id)
            database = _Database()
            consolidator = _CapabilityConsolidator()
            result = run_semantic_agent_pipeline(
                work=work,
                run_root=run,
                run_id="run-1",
                tenant_id="tenant-1",
                repository_id="repo",
                source_hash="a" * 64,
                analyst_elements=detected,
                extraction=extraction,
                normalized_graph=normalize_graphify_json({"nodes": []}),
                admin=database,
                index=InMemoryKnowledgeIndex(),
                infrastructure_agent=_InfrastructureAgent(system_id),
                module_agent_factory=_ModuleAgent,
                capability_consolidator=consolidator,
                preliminary_scans=preliminary_scans,
            )

            self.assertFalse((work / "secrets.py").exists())
            self.assertEqual({item.kind for item in result.elements}, {ElementKind.CONTAINER, ElementKind.COMPONENT})
            container = next(item for item in result.elements if item.kind == ElementKind.CONTAINER)
            component = next(item for item in result.elements if item.kind == ElementKind.COMPONENT)
            self.assertEqual(container.parent_id, system_id)
            self.assertEqual(component.parent_id, container.id)
            self.assertEqual(len(result.relationships), 0)
            self.assertEqual(consolidator.calls, 1)
            self.assertEqual(len(result.metadata["consolidacion_capacidades"]), 1)
            self.assertTrue(result.metadata["reparacion_capacidades"]["estabilizada"])
            self.assertTrue((run / "semantic" / "chunks.json").is_file())
            self.assertTrue((run / "merge" / "capability-consolidation.json").is_file())
            self.assertTrue((run / "merge" / "capability-consolidation-01.json").is_file())
            self.assertTrue((run / "merge" / "capability-repair.json").is_file())
            self.assertTrue(any(
                row.get("metadata", {}).get("stage") == "capability_consolidation"
                for row in database.rows["ejecuciones_agente"]
            ))
            repair_rows = [
                row for row in database.rows["ejecuciones_agente"]
                if row.get("metadata", {}).get("stage") == "capability_consolidation"
            ]
            self.assertEqual([row["metadata"]["iteration"] for row in repair_rows], [1])
            scan = json.loads((run / "semantic" / "security-scan.json").read_text(encoding="utf-8"))
            self.assertTrue(any(item["status"] == "excluded" for item in json.loads((run / "semantic" / "parser-report.json").read_text(encoding="utf-8"))["files"]))
            self.assertNotIn("do-not-store", json.dumps(scan))
            self.assertGreaterEqual(len(database.rows["consultas_rag"]), 2)
            self.assertNotIn("orders", json.dumps(database.rows))
            self.assertNotIn("do-not-store", json.dumps(database.rows))

    @staticmethod
    def _chunk(source_path, imports=(), chunk_id="chunk"):
        return SemanticChunk(
            id=chunk_id,
            chunk_hash="hash",
            source_hash="a" * 64,
            tenant_id="tenant",
            repository_id="repo",
            source_path=source_path,
            language=Language.PYTHON,
            parser_version="test",
            symbol=SymbolRecord(
                name="name", qualified_name="q", kind=SymbolKind.MODULE,
                visibility=Visibility.PUBLIC, start_line=1, end_line=10,
            ),
            imports=tuple(ImportRecord(module=module, line=1) for module in imports),
            dependencies=tuple(),
            publication_policy=PublicationPolicy.INDEX,
            content="source",
        )

    def test_path_matches_import_rejects_package_prefix_false_positives(self):
        self.assertTrue(_path_matches_import("repo/app/services/__init__.py", "app.services"))
        self.assertTrue(_path_matches_import("repo/app/services/security.py", "app.services.security"))
        self.assertFalse(_path_matches_import("repo/app/services/authentication.py", "app.services"))
        self.assertFalse(_path_matches_import("repo/app/services/articles.py", "app.services"))

    def test_evidence_coherence_rejects_cross_capability_chunks(self):
        users = self._merged_element("users", "Gestor de Usuarios", ElementKind.COMPONENT, "api")
        article_chunk = self._chunk("repo/app/db/repositories/articles.py")
        user_chunk = self._chunk("repo/app/db/repositories/users.py")
        self.assertFalse(_chunk_coherente_con_componente(article_chunk, users))
        self.assertTrue(_chunk_coherente_con_componente(user_chunk, users))

    def test_augment_marks_relationships_without_direct_import(self):
        comments = self._merged_element("comments", "Gestión de Comentarios", ElementKind.COMPONENT, "api", "chunk-comments")
        articles = self._merged_element("articles", "Gestión de Artículos", ElementKind.COMPONENT, "api", "chunk-articles")
        server = self._merged_element("server", "Servidor de la Aplicación", ElementKind.CONTAINER, "system", "chunk-server")
        database = self._merged_element("db", "Base de datos PostgreSQL", ElementKind.CONTAINER, "system", "chunk-db", "PostgreSQL")
        chunk_comments = self._chunk("repo/app/api/routes/comments.py", ("app.services.articles",), "chunk-comments")
        chunk_articles = self._chunk("repo/app/services/articles.py", (), "chunk-articles")
        chunk_server = self._chunk("repo/app/main.py", (), "chunk-server")
        chunk_db = self._chunk("repo/app/db/session.py", (), "chunk-db")
        graph = MergedAgentGraph(
            elements=(server, database, comments, articles),
            relationships=(
                MergedRelationship(
                    id="r1", source_id="comments", target_id="articles",
                    description="Gestión de Comentarios depende de Gestión de Artículos",
                    technology="Python import", evidence_chunk_ids=("chunk-comments",),
                ),
                MergedRelationship(
                    id="r2", source_id="articles", target_id="comments",
                    description="Gestión de Artículos depende de Gestión de Comentarios",
                    technology="Python import", evidence_chunk_ids=("chunk-articles",),
                ),
            ),
            conflicts=(), orphans=(),
        )

        result = _augment_architecture_graph(
            graph,
            (chunk_comments, chunk_articles, chunk_server, chunk_db),
            (),
            "system",
            "RealWorld",
        )

        by_pair = {(item.source_id, item.target_id): item for item in result.relationships}
        self.assertIn(("comments", "articles"), by_pair)
        self.assertNotIn("sin_evidencia_import", by_pair[("comments", "articles")].tags)
        self.assertIn(("articles", "comments"), by_pair)
        self.assertIn("sin_evidencia_import", by_pair[("articles", "comments")].tags)


if __name__ == "__main__":
    unittest.main()
