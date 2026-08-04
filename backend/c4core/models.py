from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CoreModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceSource(StrEnum):
    INVENTORY = "inventory"
    MANIFEST = "manifest"
    ANALYST = "analyst"
    GRAPHIFY = "graphify"
    SEMANTIC = "semantic"
    AGENT = "agent"


class EvidenceKind(StrEnum):
    FILE = "file"
    MANIFEST = "manifest"
    ANALYST_CONTEXT = "analyst_context"
    GRAPH_NODE = "graph_node"
    GRAPH_RELATION = "graph_relation"
    GRAPH_DOCUMENT = "graph_document"
    SEMANTIC_CHUNK = "semantic_chunk"
    SECURITY_SCAN = "security_scan"
    KNOWLEDGE_INDEX = "knowledge_index"
    AGENT_OUTPUT = "agent_output"


class Provenance(StrEnum):
    DETECTED = "detected"
    ANALYST_PROVIDED = "analyst_provided"
    INFERRED = "inferred"


class DecisionValue(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class ElementKind(StrEnum):
    PERSON = "person"
    SOFTWARE_SYSTEM = "software_system"
    EXTERNAL_SYSTEM = "external_system"
    CONTAINER = "container"
    COMPONENT = "component"


class C4Level(StrEnum):
    CONTEXT = "context"
    CONTAINER = "container"
    COMPONENT = "component"


class ArtifactFormat(StrEnum):
    STRUCTURIZR_DSL = "structurizr_dsl"
    MARKDOWN = "markdown"
    DOCX = "docx"


class EvidenceRecord(CoreModel):
    id: str
    source: EvidenceSource
    kind: EvidenceKind
    locator: str
    payload: Any
    content_hash: str


class InventoryEntry(CoreModel):
    path: str
    size: int = Field(ge=0)
    sha256: str


class ManifestRecord(CoreModel):
    path: str
    manifest_type: str
    data: Any
    evidence_id: str


class AnalystContext(CoreModel):
    repository_name: str = Field(min_length=1)
    system_name: str | None = None
    purpose: str | None = None
    users: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


class ExtractionContext(CoreModel):
    repository_root: str
    analyst: AnalystContext
    inventory: tuple[InventoryEntry, ...]
    manifests: tuple[ManifestRecord, ...]
    evidence: tuple[EvidenceRecord, ...]


class NormalizedGraphNode(CoreModel):
    id: str
    name: str
    node_type: str | None = None
    path: str | None = None
    community: Any | None = None
    evidence_id: str


class NormalizedGraphRelation(CoreModel):
    id: str
    source: str
    target: str
    relation_type: str
    collection: str
    evidence_id: str


class QuarantinedGraphRelation(CoreModel):
    relation: NormalizedGraphRelation
    reason: str


class NormalizedGraph(CoreModel):
    nodes: tuple[NormalizedGraphNode, ...]
    relations: tuple[NormalizedGraphRelation, ...]
    quarantined_relations: tuple[QuarantinedGraphRelation, ...]
    evidence: tuple[EvidenceRecord, ...]


class CandidateElement(CoreModel):
    id: str
    kind: ElementKind
    name: str = Field(min_length=1)
    description: str = ""
    technology: str | None = None
    parent_id: str | None = None
    provenance: Provenance
    evidence_ids: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()


class CandidateRelationship(CoreModel):
    id: str
    source_id: str
    target_id: str
    description: str = Field(min_length=1)
    technology: str | None = None
    provenance: Provenance
    evidence_ids: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()


class HumanDecision(CoreModel):
    target_id: str
    decision: DecisionValue
    reviewer: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class ValidationIssue(CoreModel):
    code: str
    message: str
    target_id: str | None = None


class CandidateValidationResult(CoreModel):
    valid: bool
    approved_element_ids: tuple[str, ...]
    approved_relationship_ids: tuple[str, ...]
    rejected_ids: tuple[str, ...]
    issues: tuple[ValidationIssue, ...]


class C4Element(CoreModel):
    id: str
    kind: ElementKind
    name: str
    description: str = ""
    technology: str | None = None
    parent_id: str | None = None
    provenance: Provenance
    evidence_ids: tuple[str, ...]
    tags: tuple[str, ...] = ()


class C4Relationship(CoreModel):
    id: str
    source_id: str
    target_id: str
    description: str
    technology: str | None = None
    provenance: Provenance
    evidence_ids: tuple[str, ...]
    tags: tuple[str, ...] = ()


class CanonicalC4Model(CoreModel):
    model_id: str
    content_hash: str
    name: str
    description: str = ""
    elements: tuple[C4Element, ...]
    relationships: tuple[C4Relationship, ...]
    evidence: tuple[EvidenceRecord, ...]
    decisions: tuple[HumanDecision, ...] = ()


class RenderedArtifact(CoreModel):
    format: ArtifactFormat
    media_type: str
    filename: str
    content_hash: str
    content: str | bytes
