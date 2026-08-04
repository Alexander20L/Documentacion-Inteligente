from __future__ import annotations

from typing import Iterable

from .canonical import stable_hash, stable_id
from .models import (
    C4Element,
    C4Relationship,
    CandidateElement,
    CandidateRelationship,
    CanonicalC4Model,
    EvidenceRecord,
    HumanDecision,
)
from .validation import C4ValidationError, assert_valid_c4_model, validate_candidates


def assemble_canonical_model(
    name: str,
    description: str,
    elements: Iterable[CandidateElement],
    relationships: Iterable[CandidateRelationship],
    evidence: Iterable[EvidenceRecord],
    decisions: Iterable[HumanDecision] = (),
) -> CanonicalC4Model:
    element_list = tuple(elements)
    relationship_list = tuple(relationships)
    evidence_list = tuple(sorted(evidence, key=lambda item: item.id))
    decision_list = tuple(decisions)
    result = validate_candidates(element_list, relationship_list, evidence_list, decision_list)
    if not result.valid:
        raise C4ValidationError(result.issues)

    approved_elements = set(result.approved_element_ids)
    approved_relationships = set(result.approved_relationship_ids)
    canonical_elements = tuple(sorted((
        C4Element(
            id=item.id,
            kind=item.kind,
            name=item.name,
            description=item.description,
            technology=item.technology,
            parent_id=item.parent_id,
            provenance=item.provenance,
            evidence_ids=tuple(sorted(set(item.evidence_ids))),
            tags=tuple(sorted(set(item.tags))),
        )
        for item in element_list if item.id in approved_elements
    ), key=lambda item: item.id))
    canonical_relationships = tuple(sorted((
        C4Relationship(
            id=item.id,
            source_id=item.source_id,
            target_id=item.target_id,
            description=item.description,
            technology=item.technology,
            provenance=item.provenance,
            evidence_ids=tuple(sorted(set(item.evidence_ids))),
            tags=tuple(sorted(set(item.tags))),
        )
        for item in relationship_list if item.id in approved_relationships
    ), key=lambda item: item.id))
    approved_ids = approved_elements | approved_relationships
    canonical_decisions = tuple(sorted((
        item for item in decision_list
        if item.target_id in approved_ids
    ), key=lambda item: item.target_id))
    payload = {
        "name": name,
        "description": description,
        "elements": canonical_elements,
        "relationships": canonical_relationships,
        "evidence": evidence_list,
        "decisions": canonical_decisions,
    }
    content_hash = stable_hash(payload)
    model = CanonicalC4Model(
        model_id=stable_id("c4model", content_hash),
        content_hash=content_hash,
        name=name,
        description=description,
        elements=canonical_elements,
        relationships=canonical_relationships,
        evidence=evidence_list,
        decisions=canonical_decisions,
    )
    assert_valid_c4_model(model)
    return model
