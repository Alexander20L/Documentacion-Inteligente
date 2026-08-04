from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from c4core import ElementKind


class AgenticModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class AgentRole(StrEnum):
    INFRASTRUCTURE = "infrastructure"
    MODULE = "module"


class AgentMetadata(AgenticModel):
    agent_id: str = Field(min_length=1)
    role: AgentRole
    module_id: str | None = None
    model: str = Field(min_length=1)


class RetrievalChunk(AgenticModel):
    id: str = Field(min_length=1)
    content: str
    locator: str | None = None


class FragmentElement(AgenticModel):
    local_id: str = Field(min_length=1)
    kind: ElementKind
    name: str = Field(min_length=1)
    description: str = ""
    technology: str | None = None
    parent_ref: str | None = None
    semantic_key: str | None = None
    qualified_symbol: str | None = None
    path: str | None = None
    module: str | None = None
    evidence_chunk_ids: tuple[str, ...] = Field(min_length=1)
    provenance: Literal["inferred"] = "inferred"


class FragmentRelationship(AgenticModel):
    local_id: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    target_ref: str = Field(min_length=1)
    description: str = Field(min_length=1)
    technology: str | None = None
    evidence_chunk_ids: tuple[str, ...] = Field(min_length=1)
    provenance: Literal["inferred"] = "inferred"


class UnresolvedReference(AgenticModel):
    owner_local_id: str = Field(min_length=1)
    reference: str = Field(min_length=1)
    field: Literal["parent", "source", "target", "other"]
    reason: str = Field(min_length=1)
    evidence_chunk_ids: tuple[str, ...] = ()


class AgentGraphFragment(AgenticModel):
    fragment_id: str = Field(min_length=1)
    metadata: AgentMetadata
    elements: tuple[FragmentElement, ...] = ()
    relationships: tuple[FragmentRelationship, ...] = ()
    unresolved_references: tuple[UnresolvedReference, ...] = ()


class ConflictKind(StrEnum):
    TYPE = "type"
    PARENT = "parent"
    TECHNOLOGY = "technology"
    SEMANTIC = "semantic"


class MergeConflict(AgenticModel):
    id: str
    identity: str
    kind: ConflictKind
    candidate_ids: tuple[str, ...]
    values: tuple[str, ...]
    evidence_chunk_ids: tuple[str, ...]
    reason: str


class OrphanCandidate(AgenticModel):
    id: str
    candidate_kind: Literal["element", "relationship", "reference"]
    candidate_id: str
    reason: str
    missing_references: tuple[str, ...] = ()
    evidence_chunk_ids: tuple[str, ...] = ()


class MergedElement(AgenticModel):
    id: str
    identity: str
    kind: ElementKind
    name: str
    description: str = ""
    technology: str | None = None
    parent_id: str | None = None
    evidence_chunk_ids: tuple[str, ...]
    agent_ids: tuple[str, ...]
    module_ids: tuple[str, ...]
    models: tuple[str, ...]
    provenance: Literal["inferred"] = "inferred"


class MergedRelationship(AgenticModel):
    id: str
    source_id: str
    target_id: str
    description: str
    technology: str | None = None
    evidence_chunk_ids: tuple[str, ...]
    provenance: Literal["inferred"] = "inferred"
    tags: tuple[str, ...] = ()


class MergedAgentGraph(AgenticModel):
    elements: tuple[MergedElement, ...]
    relationships: tuple[MergedRelationship, ...]
    conflicts: tuple[MergeConflict, ...] = ()
    orphans: tuple[OrphanCandidate, ...] = ()


class CapabilityGroup(AgenticModel):
    capability_key: str = Field(min_length=2, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    canonical_name: str = Field(min_length=3)
    canonical_description: str = Field(min_length=8)
    member_ids: tuple[str, ...] = Field(min_length=2)
    confidence: Literal["high", "uncertain"]
    reason: str = Field(min_length=8)


class CapabilityConsolidationPlan(AgenticModel):
    groups: tuple[CapabilityGroup, ...] = ()


class FindingSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class JudgeFinding(AgenticModel):
    id: str = Field(min_length=1)
    severity: FindingSeverity
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    element_ids: tuple[str, ...] = ()
    evidence_chunk_ids: tuple[str, ...] = ()


class JudgeReport(AgenticModel):
    judge: str = Field(min_length=1)
    findings: tuple[JudgeFinding, ...] = ()
    advisory_only: Literal[True] = True
