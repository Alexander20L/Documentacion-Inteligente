import importlib.util
import unittest

from c4core import (
    CandidateElement,
    CandidateRelationship,
    DecisionValue,
    ElementKind,
    EvidenceKind,
    EvidenceRecord,
    EvidenceSource,
    HumanDecision,
    Provenance,
    assemble_canonical_model,
    canonical_json,
    normalize_graphify_json,
    render_docx,
    render_markdown,
    render_structurizr_dsl,
    stable_hash,
    stable_id,
    validate_candidates,
)


def evidence(identifier: str = "ev_1") -> EvidenceRecord:
    payload = {"path": "src/main.py", "unknown": {"kept": True}}
    return EvidenceRecord(
        id=identifier,
        source=EvidenceSource.GRAPHIFY,
        kind=EvidenceKind.GRAPH_NODE,
        locator="graph.json#/nodes/0",
        payload=payload,
        content_hash=stable_hash(payload),
    )


class CanonicalHashTests(unittest.TestCase):
    def test_hash_and_id_ignore_mapping_insertion_order(self) -> None:
        left = {"name": "api", "metadata": {"b": 2, "a": 1}}
        right = {"metadata": {"a": 1, "b": 2}, "name": "api"}
        self.assertEqual(canonical_json(left), canonical_json(right))
        self.assertEqual(stable_hash(left), stable_hash(right))
        self.assertEqual(stable_id("element", left), stable_id("element", right))


class GraphifyNormalizationTests(unittest.TestCase):
    def test_preserves_community_zero_and_reads_links_and_edges(self) -> None:
        graph = {
            "nodes": [
                {"id": 0, "name": "API", "community": 0, "future_field": {"x": 1}},
                {"id": "b", "label": "Database", "group": 2},
            ],
            "links": [{"source": 0, "target": "b", "type": "writes"}],
            "edges": [
                {"from": {"id": "b"}, "to": {"id": 0}, "label": "reads"},
                {"source": 0, "target": "missing", "custom": "preserved"},
            ],
            "unknown_top_level": [1, 2, 3],
        }
        normalized = normalize_graphify_json(graph)
        self.assertEqual(normalized.nodes[0].community, 0)
        self.assertEqual(normalized.nodes[0].id, "0")
        self.assertEqual({item.collection for item in normalized.relations}, {"links", "edges"})
        self.assertEqual(len(normalized.quarantined_relations), 1)
        self.assertIn("missing", normalized.quarantined_relations[0].reason)
        document = next(item for item in normalized.evidence if item.kind == EvidenceKind.GRAPH_DOCUMENT)
        self.assertEqual(document.payload["unknown_top_level"], [1, 2, 3])
        relation_evidence = next(item for item in normalized.evidence if item.locator == "graph.json#/edges/1")
        self.assertEqual(relation_evidence.payload["custom"], "preserved")
        self.assertEqual(len(normalized.evidence), 1 + 2 + 1 + 2)


class CandidateValidationTests(unittest.TestCase):
    def test_inferred_candidate_requires_explicit_approval(self) -> None:
        ev = evidence()
        system = CandidateElement(
            id="system",
            kind=ElementKind.SOFTWARE_SYSTEM,
            name="System",
            provenance=Provenance.INFERRED,
            evidence_ids=(ev.id,),
        )
        without_decision = validate_candidates((system,), (), (ev,))
        self.assertFalse(without_decision.valid)
        self.assertEqual(without_decision.issues[0].code, "inference_requires_decision")
        decision = HumanDecision(target_id="system", decision=DecisionValue.APPROVE, reviewer="architect", rationale="Confirmed boundary")
        approved = validate_candidates(
            (system,),
            (),
            (ev,),
            (decision,),
        )
        self.assertTrue(approved.valid)
        self.assertEqual(approved.approved_element_ids, ("system",))
        model = assemble_canonical_model("System", "", (system,), (), (ev,), (item for item in (decision,)))
        self.assertEqual(model.decisions, (decision,))
        self.assertIn("Confirmed boundary", render_markdown(model))

    def test_enforces_evidence_and_c4_hierarchy(self) -> None:
        ev = evidence()
        component = CandidateElement(
            id="component",
            kind=ElementKind.COMPONENT,
            name="Component",
            parent_id="system",
            provenance=Provenance.DETECTED,
            evidence_ids=("unknown",),
        )
        system = CandidateElement(
            id="system",
            kind=ElementKind.SOFTWARE_SYSTEM,
            name="System",
            provenance=Provenance.DETECTED,
            evidence_ids=(ev.id,),
        )
        result = validate_candidates((component, system), (), (ev,))
        self.assertEqual({item.code for item in result.issues}, {"unknown_evidence", "invalid_parent_kind"})

    def test_pre_review_validation_accepts_inferred_relationship_endpoints(self) -> None:
        ev = evidence()
        system = CandidateElement(
            id="system", kind=ElementKind.SOFTWARE_SYSTEM, name="System",
            provenance=Provenance.DETECTED, evidence_ids=(ev.id,),
        )
        container = CandidateElement(
            id="api", kind=ElementKind.CONTAINER, name="API", parent_id=system.id,
            provenance=Provenance.INFERRED, evidence_ids=(ev.id,),
        )
        relationship = CandidateRelationship(
            id="uses", source_id=system.id, target_id=container.id, description="Uses",
            provenance=Provenance.INFERRED, evidence_ids=(ev.id,),
        )
        result = validate_candidates(
            (system, container), (relationship,), (ev,), require_decisions=False,
        )
        self.assertTrue(result.valid)
        self.assertEqual(result.approved_element_ids, ("api", "system"))
        self.assertEqual(result.approved_relationship_ids, ("uses",))


class RenderingTests(unittest.TestCase):
    def build_model(self):
        ev = evidence()
        system = CandidateElement(
            id="system",
            kind=ElementKind.SOFTWARE_SYSTEM,
            name='Order "System"',
            description="Processes orders",
            provenance=Provenance.DETECTED,
            evidence_ids=(ev.id,),
        )
        container = CandidateElement(
            id="api",
            kind=ElementKind.CONTAINER,
            name="API",
            description="HTTP entry point",
            technology="FastAPI",
            parent_id=system.id,
            provenance=Provenance.DETECTED,
            evidence_ids=(ev.id,),
        )
        relationship = CandidateRelationship(
            id="uses",
            source_id=system.id,
            target_id=container.id,
            description="Delegates requests",
            provenance=Provenance.DETECTED,
            evidence_ids=(ev.id,),
        )
        return assemble_canonical_model("Orders", "Approved architecture", (container, system), (relationship,), (ev,))

    def test_dsl_and_markdown_are_deterministic_and_traceable(self) -> None:
        model = self.build_model()
        dsl = render_structurizr_dsl(model)
        markdown = render_markdown(model)
        self.assertEqual(dsl, render_structurizr_dsl(model))
        self.assertEqual(markdown, render_markdown(model))
        self.assertIn('Order \\"System\\"', dsl)
        self.assertIn("container", dsl)
        self.assertIn("## Evidence index", markdown)
        self.assertIn("`ev_1`", markdown)
        markdown_with_diagram = render_markdown(model, ("diagrams/context.svg",))
        self.assertIn("![Context](diagrams/context.svg)", markdown_with_diagram)

    @unittest.skipUnless(importlib.util.find_spec("docx"), "python-docx is not installed")
    def test_docx_bytes_are_deterministic(self) -> None:
        model = self.build_model()
        first = render_docx(model)
        second = render_docx(model)
        self.assertEqual(first, second)
        self.assertTrue(first.startswith(b"PK"))


if __name__ == "__main__":
    unittest.main()
