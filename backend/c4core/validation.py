from __future__ import annotations

from collections import Counter
from typing import Iterable

from .canonical import stable_hash, stable_id
from .models import (
    C4Element,
    C4Relationship,
    CandidateElement,
    CandidateRelationship,
    CandidateValidationResult,
    CanonicalC4Model,
    DecisionValue,
    ElementKind,
    EvidenceRecord,
    HumanDecision,
    Provenance,
    ValidationIssue,
)


_PARENT_KIND = {
    ElementKind.CONTAINER: ElementKind.SOFTWARE_SYSTEM,
    ElementKind.COMPONENT: ElementKind.CONTAINER,
}


class C4ValidationError(ValueError):
    def __init__(self, issues: Iterable[ValidationIssue]):
        self.issues = tuple(issues)
        super().__init__("; ".join(issue.message for issue in self.issues))


def _duplicates(values: Iterable[str]) -> set[str]:
    return {value for value, count in Counter(values).items() if count > 1}


def validate_candidates(
    elements: Iterable[CandidateElement],
    relationships: Iterable[CandidateRelationship],
    evidence: Iterable[EvidenceRecord],
    decisions: Iterable[HumanDecision] = (),
    *,
    require_decisions: bool = True,
) -> CandidateValidationResult:
    element_list = tuple(elements)
    relationship_list = tuple(relationships)
    evidence_ids = {item.id for item in evidence}
    issues: list[ValidationIssue] = []

    all_ids = [item.id for item in (*element_list, *relationship_list)]
    for duplicate in sorted(_duplicates(all_ids)):
        issues.append(ValidationIssue(code="duplicate_id", target_id=duplicate, message=f"Duplicate candidate id: {duplicate}"))

    decision_list = tuple(decisions)
    for duplicate in sorted(_duplicates(item.target_id for item in decision_list)):
        issues.append(ValidationIssue(code="duplicate_decision", target_id=duplicate, message=f"Multiple human decisions for: {duplicate}"))
    decision_by_id = {item.target_id: item for item in decision_list}
    candidate_ids = set(all_ids)
    for target_id in sorted(set(decision_by_id) - candidate_ids):
        issues.append(ValidationIssue(code="unknown_decision_target", target_id=target_id, message=f"Decision references unknown candidate: {target_id}"))

    element_by_id = {item.id: item for item in element_list}
    rejected = {
        target_id
        for target_id, decision in decision_by_id.items()
        if decision.decision == DecisionValue.REJECT
    }

    def check_grounding(item: CandidateElement | CandidateRelationship) -> None:
        if not item.evidence_ids:
            issues.append(ValidationIssue(code="missing_evidence", target_id=item.id, message=f"Candidate has no evidence: {item.id}"))
        for evidence_id in sorted(set(item.evidence_ids) - evidence_ids):
            issues.append(ValidationIssue(code="unknown_evidence", target_id=item.id, message=f"Candidate {item.id} references unknown evidence: {evidence_id}"))
        if require_decisions and item.provenance == Provenance.INFERRED:
            decision = decision_by_id.get(item.id)
            if decision is None:
                issues.append(ValidationIssue(code="inference_requires_decision", target_id=item.id, message=f"Inferred candidate requires a human decision: {item.id}"))

    for element in element_list:
        check_grounding(element)
        required_parent_kind = _PARENT_KIND.get(element.kind)
        if required_parent_kind is None:
            if element.parent_id is not None:
                issues.append(ValidationIssue(code="invalid_parent", target_id=element.id, message=f"{element.kind} cannot have a parent: {element.id}"))
            continue
        parent = element_by_id.get(element.parent_id or "")
        if parent is None:
            issues.append(ValidationIssue(code="missing_parent", target_id=element.id, message=f"Missing parent for {element.id}"))
        elif parent.kind != required_parent_kind:
            issues.append(ValidationIssue(code="invalid_parent_kind", target_id=element.id, message=f"Parent of {element.id} must be {required_parent_kind}"))

    approved_elements = {
        item.id
        for item in element_list
        if item.id not in rejected
        and (
            not require_decisions
            or item.provenance != Provenance.INFERRED
            or (
                decision_by_id.get(item.id) is not None
                and decision_by_id[item.id].decision == DecisionValue.APPROVE
            )
        )
    }
    for element in element_list:
        if element.id in approved_elements and element.parent_id is not None and element.parent_id not in approved_elements:
            issues.append(ValidationIssue(code="unapproved_parent", target_id=element.id, message=f"Approved element has an unapproved parent: {element.id}"))
    for relation in relationship_list:
        check_grounding(relation)
        if relation.source_id == relation.target_id:
            issues.append(ValidationIssue(code="self_relationship", target_id=relation.id, message=f"Self relationship is not allowed: {relation.id}"))
        for endpoint in (relation.source_id, relation.target_id):
            if endpoint not in element_by_id:
                issues.append(ValidationIssue(code="unknown_endpoint", target_id=relation.id, message=f"Relationship {relation.id} references unknown element: {endpoint}"))
            elif endpoint not in approved_elements and relation.id not in rejected:
                issues.append(ValidationIssue(code="unapproved_endpoint", target_id=relation.id, message=f"Relationship {relation.id} references unapproved element: {endpoint}"))

    approved_relationships = {
        item.id
        for item in relationship_list
        if item.id not in rejected
        and item.source_id in approved_elements
        and item.target_id in approved_elements
        and (
            not require_decisions
            or item.provenance != Provenance.INFERRED
            or (
                decision_by_id.get(item.id) is not None
                and decision_by_id[item.id].decision == DecisionValue.APPROVE
            )
        )
    }
    return CandidateValidationResult(
        valid=not issues,
        approved_element_ids=tuple(sorted(approved_elements)),
        approved_relationship_ids=tuple(sorted(approved_relationships)),
        rejected_ids=tuple(sorted(rejected & candidate_ids)),
        issues=tuple(issues),
    )


def validate_c4_model(model: CanonicalC4Model) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []
    element_by_id: dict[str, C4Element] = {item.id: item for item in model.elements}
    evidence_ids = {item.id for item in model.evidence}
    candidate_ids = {item.id for item in (*model.elements, *model.relationships)}
    decision_by_id = {item.target_id: item for item in model.decisions}
    if not any(item.kind == ElementKind.SOFTWARE_SYSTEM for item in model.elements):
        issues.append(ValidationIssue(code="missing_software_system", message="Canonical C4 model requires a software system"))
    for duplicate in sorted(_duplicates(item.id for item in model.evidence)):
        issues.append(ValidationIssue(code="duplicate_evidence", target_id=duplicate, message=f"Duplicate evidence: {duplicate}"))
    for duplicate in sorted(_duplicates(item.target_id for item in model.decisions)):
        issues.append(ValidationIssue(code="duplicate_decision", target_id=duplicate, message=f"Multiple canonical decisions for: {duplicate}"))
    for target_id in sorted(set(decision_by_id) - candidate_ids):
        issues.append(ValidationIssue(code="unknown_decision_target", target_id=target_id, message=f"Canonical decision references unknown item: {target_id}"))
    for decision in model.decisions:
        if decision.decision != DecisionValue.APPROVE:
            issues.append(ValidationIssue(code="non_approval_decision", target_id=decision.target_id, message=f"Canonical model contains a non-approval decision: {decision.target_id}"))
    for duplicate in sorted(_duplicates(item.id for item in model.elements)):
        issues.append(ValidationIssue(code="duplicate_element", target_id=duplicate, message=f"Duplicate element: {duplicate}"))
    for duplicate in sorted(_duplicates(item.id for item in model.relationships)):
        issues.append(ValidationIssue(code="duplicate_relationship", target_id=duplicate, message=f"Duplicate relationship: {duplicate}"))
    for duplicate in sorted({item.id for item in model.elements} & {item.id for item in model.relationships}):
        issues.append(ValidationIssue(code="duplicate_model_id", target_id=duplicate, message=f"Element and relationship share an id: {duplicate}"))

    for item in model.evidence:
        try:
            expected_hash = stable_hash(item.payload)
        except (TypeError, ValueError) as error:
            issues.append(ValidationIssue(code="invalid_evidence_payload", target_id=item.id, message=f"Evidence payload is not canonicalizable: {item.id}: {error}"))
        else:
            if item.content_hash != expected_hash:
                issues.append(ValidationIssue(code="evidence_hash_mismatch", target_id=item.id, message=f"Evidence hash mismatch: {item.id}"))

    for element in model.elements:
        if element.provenance == Provenance.INFERRED and (
            element.id not in decision_by_id
            or decision_by_id[element.id].decision != DecisionValue.APPROVE
        ):
            issues.append(ValidationIssue(code="unapproved_inference", target_id=element.id, message=f"Canonical inference lacks approval: {element.id}"))
        if not element.evidence_ids:
            issues.append(ValidationIssue(code="missing_evidence", target_id=element.id, message=f"Canonical element has no evidence: {element.id}"))
        required_parent_kind = _PARENT_KIND.get(element.kind)
        parent = element_by_id.get(element.parent_id or "")
        if required_parent_kind is None and element.parent_id is not None:
            issues.append(ValidationIssue(code="invalid_parent", target_id=element.id, message=f"{element.kind} cannot have a parent: {element.id}"))
        elif required_parent_kind is not None and (parent is None or parent.kind != required_parent_kind):
            issues.append(ValidationIssue(code="invalid_hierarchy", target_id=element.id, message=f"Invalid C4 hierarchy for: {element.id}"))
        for evidence_id in element.evidence_ids:
            if evidence_id not in evidence_ids:
                issues.append(ValidationIssue(code="unknown_evidence", target_id=element.id, message=f"Unknown evidence {evidence_id} on {element.id}"))

    for relation in model.relationships:
        if relation.provenance == Provenance.INFERRED and (
            relation.id not in decision_by_id
            or decision_by_id[relation.id].decision != DecisionValue.APPROVE
        ):
            issues.append(ValidationIssue(code="unapproved_inference", target_id=relation.id, message=f"Canonical inference lacks approval: {relation.id}"))
        if not relation.evidence_ids:
            issues.append(ValidationIssue(code="missing_evidence", target_id=relation.id, message=f"Canonical relationship has no evidence: {relation.id}"))
        if relation.source_id == relation.target_id:
            issues.append(ValidationIssue(code="self_relationship", target_id=relation.id, message=f"Self relationship is not allowed: {relation.id}"))
        for endpoint in (relation.source_id, relation.target_id):
            if endpoint not in element_by_id:
                issues.append(ValidationIssue(code="unknown_endpoint", target_id=relation.id, message=f"Unknown endpoint {endpoint} on {relation.id}"))
        for evidence_id in relation.evidence_ids:
            if evidence_id not in evidence_ids:
                issues.append(ValidationIssue(code="unknown_evidence", target_id=relation.id, message=f"Unknown evidence {evidence_id} on {relation.id}"))
    payload = {
        "name": model.name,
        "description": model.description,
        "elements": model.elements,
        "relationships": model.relationships,
        "evidence": model.evidence,
        "decisions": model.decisions,
    }
    try:
        expected_content_hash = stable_hash(payload)
    except (TypeError, ValueError):
        pass
    else:
        if model.content_hash != expected_content_hash:
            issues.append(ValidationIssue(code="model_hash_mismatch", target_id=model.model_id, message="Canonical model content hash mismatch"))
        if model.model_id != stable_id("c4model", expected_content_hash):
            issues.append(ValidationIssue(code="model_id_mismatch", target_id=model.model_id, message="Canonical model id mismatch"))
    return tuple(issues)


def assert_valid_c4_model(model: CanonicalC4Model) -> None:
    issues = validate_c4_model(model)
    if issues:
        raise C4ValidationError(issues)
