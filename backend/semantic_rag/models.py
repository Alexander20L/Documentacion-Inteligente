from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class SemanticModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Language(StrEnum):
    PYTHON = "python"
    TYPESCRIPT = "typescript"


class SymbolKind(StrEnum):
    MODULE = "module"
    CLASS = "class"
    METHOD = "method"
    FUNCTION = "function"
    ROUTE = "route"


class Visibility(StrEnum):
    PUBLIC = "public"
    PROTECTED = "protected"
    PRIVATE = "private"


class PublicationPolicy(StrEnum):
    INDEX = "index"
    REDACT = "redact"
    EXCLUDE = "exclude"


class FindingSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class ImportRecord(SemanticModel):
    module: str
    names: tuple[str, ...] = ()
    alias: str | None = None
    line: int = Field(ge=1)


class DependencyRecord(SemanticModel):
    target: str
    kind: str
    line: int = Field(ge=1)


class SymbolRecord(SemanticModel):
    name: str
    qualified_name: str
    kind: SymbolKind
    visibility: Visibility
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    signature: str = ""
    docstring: str | None = None
    decorators: tuple[str, ...] = ()
    bases: tuple[str, ...] = ()
    framework_roles: tuple[str, ...] = ()


class SemanticChunk(SemanticModel):
    id: str
    chunk_hash: str
    source_hash: str
    tenant_id: str
    repository_id: str
    source_path: str
    language: Language
    parser_version: str
    symbol: SymbolRecord
    content: str
    imports: tuple[ImportRecord, ...] = ()
    dependencies: tuple[DependencyRecord, ...] = ()
    publication_policy: PublicationPolicy = PublicationPolicy.INDEX
    parent_chunk_id: str | None = None


class SecurityFinding(SemanticModel):
    code: str
    severity: FindingSeverity
    path: str
    line: int | None = Field(default=None, ge=1)
    pattern: str | None = None
    message: str
    redacted: bool = False


class ScanResult(SemanticModel):
    allowed: bool
    policy: PublicationPolicy
    redacted_text: str | None = None
    findings: tuple[SecurityFinding, ...] = ()


class RetrievalHit(SemanticModel):
    chunk_id: str
    chunk_hash: str
    score: float
    content: str
    source_path: str
    qualified_symbol: str


class RetrievalAudit(SemanticModel):
    tenant_id: str
    repository_id: str
    source_hash: str
    query: str
    requested_limit: int = Field(ge=1)
    accepted_chunk_ids: tuple[str, ...] = ()
    rejected_unknown: int = Field(default=0, ge=0)
    rejected_stale: int = Field(default=0, ge=0)


class RetrievalResult(SemanticModel):
    hits: tuple[RetrievalHit, ...]
    audit: RetrievalAudit


class IndexHealth(SemanticModel):
    healthy: bool
    backend: str
    detail: str = ""
