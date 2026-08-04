from __future__ import annotations

from c4core import CandidateElement, CandidateRelationship, Provenance

from .models import MergedAgentGraph


def to_c4core_candidates(
    graph: MergedAgentGraph,
) -> tuple[tuple[CandidateElement, ...], tuple[CandidateRelationship, ...]]:
    """Adapt only merge-approved candidates; conflicts and orphans remain review data."""
    elements = tuple(CandidateElement(
        id=item.id,
        kind=item.kind,
        name=item.name,
        description=item.description,
        technology=item.technology,
        parent_id=item.parent_id,
        provenance=Provenance.INFERRED,
        evidence_ids=item.evidence_chunk_ids,
        tags=("agentic",),
    ) for item in graph.elements)
    relationships = tuple(CandidateRelationship(
        id=item.id,
        source_id=item.source_id,
        target_id=item.target_id,
        description=item.description,
        technology=item.technology,
        provenance=Provenance.INFERRED,
        evidence_ids=item.evidence_chunk_ids,
        tags=("agentic",),
    ) for item in graph.relationships)
    return elements, relationships
