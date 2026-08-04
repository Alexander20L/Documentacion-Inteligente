from __future__ import annotations

import hashlib
import os
import posixpath
import re
import time
import unicodedata
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Callable

from agentic_c4 import (
    AgentOrchestrator,
    AgentRole,
    CapabilityConsolidationPlan,
    CONSOLIDATION_PROMPT_VERSION,
    GeminiAdvisoryJudge,
    GeminiC4Agent,
    GeminiCapabilityConsolidator,
    JudgeReport,
    MergedAgentGraph,
    MergedElement,
    MergedRelationship,
    ModuleWork,
    OllamaAdvisoryJudge,
    OllamaC4Agent,
    OllamaCapabilityConsolidator,
    RetrievalChunk,
    apply_consolidation_plan,
    deterministic_judge_report,
    merge_agent_graphs,
    to_c4core_candidates,
)
from agentic_c4.classification import capability_names_overlap, is_data_store, is_postgresql, normalized_capability_name
from c4core import (
    CandidateElement,
    CandidateRelationship,
    ElementKind,
    EvidenceKind,
    EvidenceRecord,
    EvidenceSource,
    canonical_json,
    stable_hash,
    stable_id,
)
from semantic_rag import (
    DifyConfig,
    DifyKnowledgeIndex,
    InMemoryKnowledgeIndex,
    KnowledgeIndex,
    PythonSemanticParser,
    SecurityScanner,
    SemanticChunk,
    TypeScriptSemanticParser,
)


PROMPT_VERSION = "semantic-agent-v13"


@dataclass(frozen=True)
class SemanticAgentResult:
    elements: tuple[CandidateElement, ...]
    relationships: tuple[CandidateRelationship, ...]
    evidence: tuple[EvidenceRecord, ...]
    metadata: dict[str, Any]
    artifact_paths: tuple[Path, ...]


def _write_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(canonical_json(value), encoding="utf-8", newline="\n")
    temporary.replace(path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _insert(admin: Any, table: str, row: dict[str, Any]) -> dict[str, Any]:
    result = admin.table(table).insert(row).execute()
    if not result.data:
        raise RuntimeError(f"No se pudo registrar auditoría en {table}")
    return dict(result.data[0])


def _update(admin: Any, table: str, row_id: str, values: dict[str, Any]) -> None:
    admin.table(table).update(values).eq("id", row_id).execute()


def _evidence(source: EvidenceSource, kind: EvidenceKind, locator: str, payload: Any, *, evidence_id: str | None = None, content_hash: str | None = None) -> EvidenceRecord:
    return EvidenceRecord(
        id=evidence_id or stable_id("evidence", source.value, kind.value, locator, stable_hash(payload)),
        source=source,
        kind=kind,
        locator=locator,
        payload=payload,
        content_hash=content_hash or stable_hash(payload),
    )


def _module_id(chunk: SemanticChunk) -> str:
    parts = Path(chunk.source_path).parts
    lower = [part.casefold() for part in parts]
    if "tests" in lower:
        index = lower.index("tests")
        return "/".join(parts[:index + 1])
    if "app" in lower:
        index = lower.index("app")
        return "/".join(parts[:index + 2]) if index + 2 < len(parts) else "/".join(parts[:index + 1])
    if "src" in lower and len(parts) > lower.index("src") + 1:
        index = lower.index("src")
        return "/".join(parts[:index + 3]) if index + 3 < len(parts) else "/".join(parts[:-1])
    package_parts = list(parts[:-1])
    if len(package_parts) > 2:
        package_parts = package_parts[:2]
    return "/".join(package_parts) or Path(chunk.source_path).stem


def _hit_in_agent_scope(source_path: str, module_id: str | None) -> bool:
    normalized = source_path.replace("\\", "/").strip("/")
    parts = {part.casefold() for part in normalized.split("/")}
    if "tests" in parts:
        return False
    if module_id is None:
        return True
    module = module_id.replace("\\", "/").strip("/")
    return normalized == module or normalized.startswith(module + "/")


def _build_module_work(chunks: tuple[SemanticChunk, ...], max_modules: int) -> tuple[ModuleWork, ...]:
    if max_modules < 1:
        raise ValueError("C4_AGENT_MAX_MODULES must be positive")
    groups: dict[str, list[SemanticChunk]] = {}
    for chunk in chunks:
        module_id = _module_id(chunk)
        if "tests" in {part.casefold() for part in module_id.split("/")}:
            continue
        groups.setdefault(module_id, []).append(chunk)
    if len(groups) > max_modules:
        ranked = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
        retained = dict(ranked[:max_modules - 1]) if max_modules > 1 else {}
        overflow = [chunk for _module_id_value, items in ranked[len(retained):] for chunk in items]
        roots = {module_id.split("/", 1)[0] for module_id in groups}
        overflow_id = f"{next(iter(roots))}/other" if len(roots) == 1 else "repository/other"
        while overflow_id in retained:
            overflow_id += "-group"
        retained[overflow_id] = overflow
        groups = retained
    return tuple(
        ModuleWork(
            module_id=module_id,
            local_chunks=tuple(
                RetrievalChunk(
                    id=item.id,
                    content=item.content,
                    locator=f"{item.source_path}#L{item.symbol.start_line}-L{item.symbol.end_line}",
                )
                for item in sorted(items, key=lambda value: (
                    {"route": 0, "class": 1, "module": 2, "function": 3, "method": 4}.get(value.symbol.kind.value, 5),
                    -len(value.dependencies),
                    value.source_path,
                    value.symbol.start_line,
                    value.id,
                ))
            ),
        )
        for module_id, items in sorted(groups.items())
    )


def _resolved_import_paths(imported: Any, chunk: SemanticChunk) -> tuple[str, ...]:
    module = imported.module
    source_path = chunk.source_path.replace("\\", "/")
    if chunk.language.value == "typescript":
        if not module.startswith("."):
            return (module.replace(".", "/"),)
        return (posixpath.normpath(posixpath.join(posixpath.dirname(source_path), module)),)
    if not module.startswith("."):
        base = module
    else:
        level = len(module) - len(module.lstrip("."))
        suffix = module[level:]
        parts = source_path.split("/")
        marker = next((index for index, part in enumerate(parts) if part in {"app", "src"}), None)
        if marker is None:
            base = suffix
        else:
            package = parts[marker:-1]
            if level > 1:
                package = package[:max(0, len(package) - level + 1)]
            base = ".".join((*package, *(suffix.split(".") if suffix else ())))
    paths = [base]
    paths.extend(f"{base}.{name}" for name in imported.names if base)
    return tuple(dict.fromkeys(paths))


def _path_matches_import(source_path: str, imported_module: str) -> bool:
    imported_path = imported_module.replace(".", "/").strip("/").casefold()
    path = source_path.replace("\\", "/").casefold()
    without_suffix = path
    for suffix in (".tsx", ".ts", ".jsx", ".js", ".py"):
        if without_suffix.endswith(suffix):
            without_suffix = without_suffix[:-len(suffix)]
            break
    if without_suffix.endswith("/index"):
        without_suffix = without_suffix[:-6]
    # Un import de paquete (p.ej. app.services) solo coincide con su __init__;
    # nunca con archivos internos arbitrarios, que generan falsos ciclos.
    if without_suffix.endswith(f"/{imported_path}/__init__") or without_suffix == f"{imported_path}/__init__":
        return True
    return (
        without_suffix == imported_path
        or without_suffix.endswith("/" + imported_path)
    )


def _chunk_coherente_con_componente(chunk: SemanticChunk, element: MergedElement) -> bool:
    """Rechaza evidencia cruzada citada por error en un fragmento.

    Un chunk cuyo archivo pertenece a otra capacidad (p.ej. repositories/articles.py
    citado en un componente de usuarios) genera relaciones falsas y ciclos. La
    coherencia se compara entre la capacidad del nombre de archivo y la del componente.
    """
    component_key = _component_capability_key(element) or _normalized_component_name(element.name)
    if not component_key:
        return True
    file_base = posixpath.basename(chunk.source_path.replace("\\", "/"))
    if file_base.endswith(".py"):
        file_base = file_base[:-3]
    elif file_base.endswith(".ts"):
        file_base = file_base[:-3]
    elif file_base.endswith(".tsx"):
        file_base = file_base[:-4]
    elif file_base.endswith(".js"):
        file_base = file_base[:-3]
    elif file_base.endswith(".jsx"):
        file_base = file_base[:-4]
    file_key = normalized_capability_name(file_base)
    if not file_key:
        return True
    return capability_names_overlap(component_key, file_key)


_COMPONENT_PLUMBING_TERMS = (
    "bootstrap", "config", "domain model", "dto", "error handling", "exception handling",
    "endpoint", "logging", "logger", "mapper", "middleware", "router", "routing", "ruta", "settings", "utility",
)
def _normalized_component_name(name: str) -> str:
    return normalized_capability_name(name)


def _component_capability_key(item: MergedElement) -> str:
    if item.identity.startswith("semantic:"):
        semantic_key = normalized_capability_name(item.identity.removeprefix("semantic:"))
        if semantic_key:
            return semantic_key
    return _normalized_component_name(item.name)


def _is_architectural_component_name(name: str) -> bool:
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").casefold().strip()
    return (
        bool(_normalized_component_name(name))
        and not any(term in normalized for term in _COMPONENT_PLUMBING_TERMS)
        and not normalized.endswith((" handler", " handlers", " manejador"))
    )


def _is_architectural_component(item: MergedElement) -> bool:
    if not _is_architectural_component_name(item.name):
        return False
    description = unicodedata.normalize("NFKD", item.description).encode("ascii", "ignore").decode("ascii").casefold()
    modules = " ".join(item.module_ids).replace("\\", "/").casefold()
    if any(marker in description for marker in ("loguru", "logging system", "logger configuration")):
        return False
    if modules.endswith("/core") and any(marker in description for marker in ("configuracion", "registro", "settings")):
        return False
    return True


def _reconcile_semantic_components(elements: list[MergedElement]) -> list[MergedElement]:
    non_components = [item for item in elements if item.kind != ElementKind.COMPONENT]
    container_keys = {
        item.id: _normalized_component_name(item.name)
        for item in non_components
        if item.kind == ElementKind.CONTAINER
    }
    groups: dict[tuple[str | None, str], list[MergedElement]] = {}
    for item in elements:
        normalized_name = _normalized_component_name(item.name)
        if (
            item.kind == ElementKind.COMPONENT
            and _is_architectural_component(item)
            and normalized_name != container_keys.get(item.parent_id)
        ):
            key = (item.parent_id, _component_capability_key(item) or normalized_name or item.id)
            groups.setdefault(key, []).append(item)

    reconciled = []
    for items in groups.values():
        representative = sorted(
            items,
            key=lambda item: (-len(item.evidence_chunk_ids), -len(item.description.strip()), item.name.casefold(), item.id),
        )[0]
        reconciled.append(representative.model_copy(update={
            "evidence_chunk_ids": tuple(sorted({value for item in items for value in item.evidence_chunk_ids}))[:5],
            "agent_ids": tuple(sorted({value for item in items for value in item.agent_ids})),
            "module_ids": tuple(sorted({value for item in items for value in item.module_ids})),
            "models": tuple(sorted({value for item in items for value in item.models})),
        }))
    return [*non_components, *reconciled]


def _reconcile_semantic_relationships(
    elements: list[MergedElement],
    relationships: list[MergedRelationship],
) -> list[MergedRelationship]:
    element_by_id = {item.id: item for item in elements}

    def endpoint_key(element_id: str) -> tuple[str, str]:
        element = element_by_id[element_id]
        if element.kind == ElementKind.COMPONENT:
            return (element.kind.value, _component_capability_key(element))
        return (element.kind.value, element.id)

    groups: dict[tuple[tuple[str, str], tuple[str, str], str | None], list[MergedRelationship]] = {}
    for relationship in relationships:
        source_key = endpoint_key(relationship.source_id)
        target_key = endpoint_key(relationship.target_id)
        if source_key == target_key:
            continue
        groups.setdefault((source_key, target_key, relationship.technology), []).append(relationship)

    reconciled = []
    for entries in groups.values():
        representative = sorted(entries, key=lambda item: item.id)[0]
        reconciled.append(representative.model_copy(update={
            "evidence_chunk_ids": tuple(sorted({
                evidence_id for item in entries for evidence_id in item.evidence_chunk_ids
            }))[:5],
        }))
    return sorted(reconciled, key=lambda item: item.id)


def _augment_architecture_graph(
    graph: MergedAgentGraph,
    chunks: tuple[SemanticChunk, ...],
    _modules: tuple[ModuleWork, ...],
    system_id: str,
    system_name: str,
) -> MergedAgentGraph:
    containers = [item for item in graph.elements if item.kind == ElementKind.CONTAINER]
    data_store_containers = [item for item in containers if is_data_store(item.name, item.technology)]
    postgresql_containers = [item for item in data_store_containers if is_postgresql(item.name, item.technology)]
    non_deployable_terms = ("config", "setting", "logging", "routing", "middleware")
    executable_containers = [
        item for item in containers
        if not any(term in item.name.casefold() for term in non_deployable_terms)
        and not is_data_store(item.name, item.technology)
    ]
    if not executable_containers:
        raise RuntimeError("C4 agent quality gate failed: no executable application container")
    executable_containers = [item.model_copy(update={"parent_id": system_id}) for item in executable_containers]
    primary_container = sorted(
        executable_containers,
        key=lambda item: (
            -sum(token in item.name.casefold() for token in ("application", "api", "service", "server")),
            item.id,
        ),
    )[0]

    refined_elements = [
        item.model_copy(update={"parent_id": system_id})
        for item in data_store_containers
        if item not in postgresql_containers
    ]
    refined_elements.extend(executable_containers)
    executable_ids = {item.id for item in executable_containers}
    for item in graph.elements:
        if item.kind != ElementKind.COMPONENT:
            continue
        if not _is_architectural_component_name(item.name):
            continue
        name = item.name
        description = item.description
        if not description.strip():
            description = f"Responsabilidades arquitectónicas representadas por {name}."
        refined_elements.append(item.model_copy(update={
            "name": name,
            "description": description,
            "parent_id": item.parent_id if item.parent_id in executable_ids else primary_container.id,
        }))
    refined_elements = _reconcile_semantic_components(refined_elements)

    database_evidence = tuple(sorted({
        chunk.id for chunk in chunks
        if any(marker in (chunk.source_path + "\n" + chunk.content).casefold() for marker in (
            "postgresdsn", "postgresql://", "postgresql+", "asyncpg", "psycopg",
        ))
    }))
    postgresql_evidence = tuple(sorted({
        evidence_id
        for item in postgresql_containers
        for evidence_id in item.evidence_chunk_ids
    } | set(database_evidence)))
    if postgresql_evidence:
        database_id = stable_id("agent_element", "deterministic", "postgresql", system_id)
        database_agent_ids = tuple(sorted({
            agent_id
            for item in postgresql_containers
            for agent_id in item.agent_ids
        } | {"deterministic-database-detector"}))
        database_module_ids = tuple(sorted({
            module_id
            for item in postgresql_containers
            for module_id in item.module_ids
        }))
        database_models = tuple(sorted({
            model
            for item in postgresql_containers
            for model in item.models
        } | {"deterministic"}))
        refined_elements.append(MergedElement(
            id=database_id,
            identity="deterministic:postgresql-database",
            kind=ElementKind.CONTAINER,
            name="Base de datos PostgreSQL",
            description="Almacén relacional persistente utilizado por la aplicación.",
            technology="PostgreSQL",
            parent_id=system_id,
            evidence_chunk_ids=postgresql_evidence[:5],
            agent_ids=database_agent_ids,
            module_ids=database_module_ids,
            models=database_models,
        ))

    components = [item for item in refined_elements if item.kind == ElementKind.COMPONENT]
    chunk_by_id = {item.id: item for item in chunks}

    def evidencia_coherente(element: MergedElement) -> tuple[str, ...]:
        return tuple(
            evidence_id
            for evidence_id in element.evidence_chunk_ids
            if _chunk_coherente_con_componente(chunk_by_id[evidence_id], element)
            if evidence_id in chunk_by_id
        )

    coherent_by_id = {item.id: evidencia_coherente(item) for item in components}
    evidence_by_pair: dict[tuple[str, str], set[str]] = {}
    technologies_by_pair: dict[tuple[str, str], set[str]] = {}
    for source in components:
        for evidence_id in coherent_by_id[source.id]:
            chunk = chunk_by_id[evidence_id]
            for imported in chunk.imports:
                matches = []
                for target in components:
                    if target.id == source.id:
                        continue
                    score = sum(
                        any(
                            _path_matches_import(chunk_by_id[target_evidence].source_path, imported_path)
                            for imported_path in _resolved_import_paths(imported, chunk)
                        )
                        for target_evidence in coherent_by_id[target.id]
                    )
                    if score:
                        matches.append((score, target))
                if not matches:
                    continue
                best_score = max(score for score, _target in matches)
                best_targets = [target for score, target in matches if score == best_score]
                if len(best_targets) == 1:
                    pair = (source.id, best_targets[0].id)
                    evidence_by_pair.setdefault(pair, set()).add(chunk.id)
                    technologies_by_pair.setdefault(pair, set()).add(
                        "TypeScript import" if chunk.language.value == "typescript" else "Python import"
                    )

    strongest_pairs = []
    pairs_by_source: dict[str, list[tuple[str, str]]] = {}
    for pair in evidence_by_pair:
        pairs_by_source.setdefault(pair[0], []).append(pair)
    for pairs in pairs_by_source.values():
        strongest_pairs.extend(sorted(
            pairs,
            key=lambda pair: (-len(evidence_by_pair[pair]), pair[1]),
        )[:3])

    relationships = []
    element_by_id = {item.id: item for item in refined_elements}
    for source_id, target_id in sorted(strongest_pairs):
        evidence_ids = evidence_by_pair[(source_id, target_id)]
        relationships.append(MergedRelationship(
            id=stable_id("agent_relationship", "source_import", source_id, target_id),
            source_id=source_id,
            target_id=target_id,
            description=f"{element_by_id[source_id].name} depende de {element_by_id[target_id].name}",
            technology=" / ".join(sorted(technologies_by_pair[(source_id, target_id)])),
            evidence_chunk_ids=tuple(sorted(evidence_ids)[:5]),
        ))
    database = next((
        item for item in refined_elements
        if item.kind == ElementKind.CONTAINER and is_postgresql(item.name, item.technology)
    ), None)
    if database:
        relationships.append(MergedRelationship(
            id=stable_id("agent_relationship", "database_protocol", primary_container.id, database.id),
            source_id=primary_container.id,
            target_id=database.id,
            description=f"{primary_container.name} lee y escribe datos de la aplicación",
            technology="PostgreSQL protocol",
            evidence_chunk_ids=database.evidence_chunk_ids,
        ))
    supported_endpoints = {(item.source_id, item.target_id) for item in relationships}
    for relation in graph.relationships:
        directed = (relation.source_id, relation.target_id)
        if directed in supported_endpoints:
            continue
        technology = relation.technology
        if technology not in {
            "Python import", "TypeScript import", "Python import / TypeScript import", "PostgreSQL protocol",
        }:
            evidence_languages = {
                chunk_by_id[evidence_id].language.value
                for evidence_id in relation.evidence_chunk_ids
                if evidence_id in chunk_by_id
            }
            if evidence_languages == {"typescript"}:
                technology = "TypeScript import"
            else:
                technology = "Python import"
        relationships.append(relation.model_copy(update={
            "tags": tuple(sorted({*relation.tags, "sin_evidencia_import"})),
            "technology": technology,
            "description": f"{relation.description} (sin evidencia de import directo)",
        }))
    relationships = _reconcile_semantic_relationships(refined_elements, relationships)
    return graph.model_copy(update={
        "elements": tuple(refined_elements),
        "relationships": tuple(relationships),
    })


def _validate_architecture_quality(graph: MergedAgentGraph) -> None:
    containers = [item for item in graph.elements if item.kind == ElementKind.CONTAINER]
    components = [item for item in graph.elements if item.kind == ElementKind.COMPONENT]
    issues = []
    if not containers:
        issues.append("no valid containers")
    if not components:
        issues.append("no valid components")
    executable_container_ids = {
        item.id for item in containers
        if not is_data_store(item.name, item.technology)
    }
    non_deployable_terms = ("config", "setting", "logging", "routing", "middleware")
    invalid_containers = [
        item.name for item in containers
        if any(term in item.name.casefold() for term in non_deployable_terms)
    ]
    if invalid_containers:
        issues.append("non-deployable containers: " + ", ".join(sorted(invalid_containers)))
    invalid_parents = [item.name for item in components if item.parent_id not in executable_container_ids]
    if invalid_parents:
        issues.append("components without an executable container parent: " + ", ".join(sorted(invalid_parents)))
    invalid_components = [item.name for item in components if not _is_architectural_component(item)]
    if invalid_components:
        issues.append("implementation-level components: " + ", ".join(sorted(invalid_components)))
    identities: dict[str, list[str]] = {}
    for item in components:
        identities.setdefault(_component_capability_key(item), []).append(item.name)
    duplicates = [names for names in identities.values() if len(names) > 1]
    if duplicates:
        issues.append("semantic duplicate components: " + "; ".join(" / ".join(sorted(names)) for names in duplicates))
    maximum_components = max(1, int(os.getenv("C4_MAX_COMPONENT_CANDIDATES", "8")))
    if len(components) > maximum_components:
        issues.append(f"too many component candidates ({len(components)} > {maximum_components})")
    unsupported = [
        item.id for item in graph.relationships
        if item.technology not in {"Python import", "TypeScript import", "Python import / TypeScript import", "PostgreSQL protocol"}
    ]
    if unsupported:
        issues.append(f"unsupported inferred relationships ({len(unsupported)})")
    maximum_relationships = max(4, len(components) * 3 + 1)
    if len(graph.relationships) > maximum_relationships:
        issues.append(f"too many inferred relationships ({len(graph.relationships)} > {maximum_relationships})")
    if len(graph.orphans) > max(5, len(graph.elements) + len(graph.relationships)):
        issues.append(f"too many orphan inferences ({len(graph.orphans)})")
    if issues:
        raise RuntimeError("C4 agent quality gate failed: " + "; ".join(issues))


def _validate_gemini_request_budget(
    module_count: int,
    *,
    judge_enabled: bool,
    consolidator_enabled: bool = True,
    max_requests: int,
) -> int:
    required = 1 + module_count + int(judge_enabled) + int(consolidator_enabled)
    if max_requests < 1:
        raise ValueError("C4_GEMINI_MAX_REQUESTS_PER_RUN must be positive")
    if required > max_requests:
        raise RuntimeError(
            f"La ejecución requiere {required} solicitudes Gemini y el presupuesto configurado es {max_requests}"
        )
    return required


def sanitize_semantic_work_copy(work: Path) -> tuple[dict[str, Any], ...]:
    """Remove denied source files and redact secrets before any analysis tool sees them."""
    scanner = SecurityScanner(excludes=tuple(filter(None, (item.strip() for item in os.getenv("C4_SEMANTIC_EXCLUDES", "").split(",")))))
    records: list[dict[str, Any]] = []
    text_suffixes = {
        ".py", ".ts", ".tsx", ".js", ".json", ".html", ".xml", ".yaml", ".yml",
        ".toml", ".ini", ".cfg", ".conf", ".properties", ".sql", ".md", ".txt",
    }
    paths = sorted(
        (item for item in work.rglob("*") if item.is_file()),
        key=lambda item: item.relative_to(work).as_posix(),
    )
    for path in paths:
        relative = path.relative_to(work).as_posix()
        is_text = path.suffix.casefold() in text_suffixes or path.name.casefold() in {
            "dockerfile", "makefile", "procfile", ".gitignore",
        }
        result = scanner.scan(
            relative,
            path.read_text(encoding="utf-8", errors="replace") if is_text else "",
        )
        records.append({
            "path": relative,
            "allowed": result.allowed,
            "policy": result.policy.value,
            "findings": [item.model_dump(mode="json") for item in result.findings],
            "stage": "pre-analysis",
        })
        if not result.allowed:
            path.unlink()
        elif is_text and result.redacted_text is not None and result.policy.value == "redact":
            temporary = path.with_name(f".{path.name}.sanitize.tmp")
            temporary.write_text(result.redacted_text, encoding="utf-8", newline="\n")
            temporary.replace(path)
    return tuple(records)


def _scan_and_parse(
    work: Path,
    *,
    tenant_id: str,
    repository_id: str,
    source_hash: str,
    run_root: Path,
    preliminary_scans: tuple[dict[str, Any], ...] = (),
) -> tuple[tuple[SemanticChunk, ...], tuple[EvidenceRecord, ...], tuple[Path, ...]]:
    scanner = SecurityScanner(excludes=tuple(filter(None, (item.strip() for item in os.getenv("C4_SEMANTIC_EXCLUDES", "").split(",")))))
    paths = sorted(
        (item for item in work.rglob("*") if item.is_file() and item.suffix.casefold() in {".py", ".ts"}),
        key=lambda item: item.relative_to(work).as_posix(),
    )
    ts_parser = TypeScriptSemanticParser() if any(item.suffix.casefold() == ".ts" for item in paths) else None
    py_parser = PythonSemanticParser()
    chunks: list[SemanticChunk] = []
    scans: list[dict[str, Any]] = list(preliminary_scans)
    parser_files: list[dict[str, Any]] = [
        {"path": item["path"], "status": "excluded", "chunks": 0}
        for item in preliminary_scans if not item["allowed"]
    ]
    for path in paths:
        relative = path.relative_to(work).as_posix()
        source = path.read_text(encoding="utf-8", errors="replace")
        scan = scanner.scan(relative, source)
        scans.append({
            "path": relative,
            "allowed": scan.allowed,
            "policy": scan.policy.value,
            "findings": [item.model_dump(mode="json") for item in scan.findings],
        })
        if not scan.allowed:
            path.unlink()
            parser_files.append({"path": relative, "status": "excluded", "chunks": 0})
            continue
        parser = ts_parser if path.suffix.casefold() == ".ts" else py_parser
        try:
            parsed = parser.parse(
                scan.redacted_text or "",
                relative,
                tenant_id=tenant_id,
                repository_id=repository_id,
                source_hash=source_hash,
                publication_policy=scan.policy,
            )
        except Exception as error:
            parser_files.append({"path": relative, "status": "error", "error": type(error).__name__, "chunks": 0})
            security_path = run_root / "semantic" / "security-scan.json"
            report_path = run_root / "semantic" / "parser-report.json"
            _write_atomic(security_path, {"files": scans})
            _write_atomic(report_path, {"files": parser_files, "status": "failed"})
            raise
        chunks.extend(parsed)
        parser_files.append({"path": relative, "status": "parsed", "parser": parser.parser_version, "chunks": len(parsed)})

    ordered = tuple(sorted(chunks, key=lambda item: item.id))
    security_path = run_root / "semantic" / "security-scan.json"
    chunks_path = run_root / "semantic" / "chunks.json"
    symbols_path = run_root / "semantic" / "ast-symbols.json"
    report_path = run_root / "semantic" / "parser-report.json"
    _write_atomic(security_path, {"files": scans})
    _write_atomic(chunks_path, {"source_hash": source_hash, "chunks": [item.model_dump(mode="json") for item in ordered]})
    _write_atomic(symbols_path, {"symbols": [item.symbol.model_dump(mode="json") | {"chunk_id": item.id, "source_path": item.source_path} for item in ordered]})
    _write_atomic(report_path, {"files": parser_files, "status": "completed", "chunk_count": len(ordered)})
    evidence = [
        _evidence(
            EvidenceSource.SEMANTIC,
            EvidenceKind.SEMANTIC_CHUNK,
            f"{item.source_path}#L{item.symbol.start_line}-L{item.symbol.end_line}",
            {
                "chunk_id": item.id,
                "language": item.language.value,
                "symbol": item.symbol.qualified_name,
                "chunk_hash": item.chunk_hash,
                "parser_version": item.parser_version,
                "publication_policy": item.publication_policy.value,
            },
            evidence_id=item.id,
        )
        for item in ordered
    ]
    evidence.append(_evidence(EvidenceSource.SEMANTIC, EvidenceKind.SECURITY_SCAN, "semantic/security-scan.json", {"sha256": hashlib.sha256(security_path.read_bytes()).hexdigest(), "files": len(scans)}))
    return ordered, tuple(evidence), (security_path, chunks_path, symbols_path, report_path)


def _agent_row(admin: Any, run_id: str, index_id: str, role: str, module_id: str | None, model: str) -> dict[str, Any]:
    return _insert(admin, "ejecuciones_agente", {
        "ejecucion_c4_id": run_id,
        "indice_conocimiento_id": index_id,
        "tipo": "analista",
        "estado": "procesando",
        "modelo": model,
        "version_prompt": PROMPT_VERSION,
        "metadata": {"role": role, "module_id": module_id},
        "entrada_sha256": stable_hash({"role": role, "module_id": module_id}),
        "started_at": _now(),
    })


def run_semantic_agent_pipeline(
    *,
    work: Path,
    run_root: Path,
    run_id: str,
    tenant_id: str,
    repository_id: str,
    source_hash: str,
    analyst_elements: tuple[CandidateElement, ...],
    extraction: Any,
    normalized_graph: Any,
    admin: Any,
    index: KnowledgeIndex | None = None,
    infrastructure_agent: Any | None = None,
    module_agent_factory: Callable[[str], Any] | None = None,
    capability_consolidator: Any | None = None,
    preliminary_scans: tuple[dict[str, Any], ...] = (),
    checkpoint: Callable[[], None] = lambda: None,
    progress: Callable[[str, int, int], None] = lambda _modulo, _completadas, _totales: None,
) -> SemanticAgentResult:
    checkpoint()
    # A reclaimed analysis run replaces incomplete audit rows deterministically.
    admin.table("consultas_rag").delete().eq("ejecucion_c4_id", run_id).execute()
    admin.table("evaluaciones_c4").delete().eq("ejecucion_c4_id", run_id).execute()
    admin.table("ejecuciones_agente").delete().eq("ejecucion_c4_id", run_id).execute()
    admin.table("indices_conocimiento").delete().eq("ejecucion_c4_id", run_id).execute()
    chunks, semantic_evidence, semantic_paths = _scan_and_parse(
        work, tenant_id=tenant_id, repository_id=repository_id, source_hash=source_hash, run_root=run_root,
        preliminary_scans=preliminary_scans,
    )
    manifest_hash = hashlib.sha256((run_root / "semantic" / "chunks.json").read_bytes()).hexdigest()
    local_index_row = _insert(admin, "indices_conocimiento", {
        "ejecucion_c4_id": run_id,
        "tipo": "local_canonico",
        "estado": "disponible",
        "manifiesto_sha256": manifest_hash,
        "cantidad_chunks": len(chunks),
        "metadata": {"source_hash": source_hash, "artifact": "semantic/chunks.json"},
        "sincronizado_at": _now(),
    })

    backend = os.getenv("C4_KNOWLEDGE_BACKEND", "dify").strip().casefold()
    if index is None:
        if backend == "memory":
            index = InMemoryKnowledgeIndex()
        elif backend == "dify":
            config = replace(DifyConfig.from_env(), mapping_path=str(run_root / "semantic" / "dify-mapping.json"))
            index = DifyKnowledgeIndex(config)
        else:
            raise ValueError("C4_KNOWLEDGE_BACKEND must be 'dify' or 'memory'")
    active_index_row = local_index_row
    if isinstance(index, DifyKnowledgeIndex):
        dataset_id = index.ensure_dataset(tenant_id=tenant_id, repository_id=repository_id, source_hash=source_hash)
        active_index_row = _insert(admin, "indices_conocimiento", {
            "ejecucion_c4_id": run_id,
            "tipo": "dify",
            "estado": "procesando",
            "manifiesto_sha256": manifest_hash,
            "cantidad_chunks": len(chunks),
            "dataset_externo_id": dataset_id,
            "metadata": {"source_hash": source_hash, "mapping": "semantic/dify-mapping.json"},
        })
        try:
            index.index_chunks(chunks)
        except Exception as error:
            _update(admin, "indices_conocimiento", active_index_row["id"], {"estado": "fallido", "error_ultimo": type(error).__name__})
            raise
        checkpoint()
        _update(admin, "indices_conocimiento", active_index_row["id"], {"estado": "disponible", "sincronizado_at": _now()})
        active_index_row.update(estado="disponible", sincronizado_at=_now())
    else:
        index.index_chunks(chunks)
    index_id = str(active_index_row["id"])
    index_evidence = _evidence(EvidenceSource.SEMANTIC, EvidenceKind.KNOWLEDGE_INDEX, "semantic/chunks.json", {
        "backend": index.health().backend,
        "manifest_sha256": manifest_hash,
        "chunk_count": len(chunks),
        "dataset_id": active_index_row.get("dataset_externo_id"),
    })

    custom_analysis_agents = infrastructure_agent is not None or module_agent_factory is not None
    consolidator_enabled = os.getenv("C4_ENABLE_CAPABILITY_CONSOLIDATOR", "true").casefold() == "true"
    max_modules = int(os.getenv("C4_AGENT_MAX_MODULES", "8"))
    modules = _build_module_work(chunks, max_modules)
    provider = os.getenv("C4_LLM_PROVIDER", "ollama").strip().casefold()
    if provider not in {"gemini", "ollama"}:
        raise RuntimeError("C4_LLM_PROVIDER must be 'ollama' or 'gemini'")
    if provider == "gemini":
        _validate_gemini_request_budget(
            len(modules),
            judge_enabled=os.getenv("C4_ENABLE_LLM_JUDGE", "false").casefold() == "true",
            consolidator_enabled=consolidator_enabled and not custom_analysis_agents,
            max_requests=int(os.getenv("C4_GEMINI_MAX_REQUESTS_PER_RUN", "20")),
        )
    chunk_by_id = {chunk.id: chunk for chunk in chunks}
    modules_by_id = {
        module.module_id: [chunk_by_id[item.id] for item in module.local_chunks]
        for module in modules
    }
    max_queries_per_agent = int(os.getenv("C4_AGENT_MAX_RETRIEVAL_QUERIES", "8"))
    max_total_queries = int(os.getenv("C4_AGENT_MAX_TOTAL_RETRIEVAL_QUERIES", "808"))
    deterministic_queries_per_agent = 2
    if max_queries_per_agent < deterministic_queries_per_agent:
        raise RuntimeError("C4_AGENT_MAX_RETRIEVAL_QUERIES must allow both deterministic queries")
    if (len(modules) + 1) * deterministic_queries_per_agent > max_total_queries:
        raise RuntimeError("El presupuesto global de consultas RAG es insuficiente para los agentes requeridos")

    infrastructure_chunks = [
        RetrievalChunk(id=item.id, content=item.content, locator=item.source_path)
        for item in chunks
        if any(marker in item.source_path.casefold() for marker in ("config", "docker", "deploy", "infra", "main.", "app."))
    ]
    for manifest in extraction.manifests:
        infrastructure_chunks.append(RetrievalChunk(id=manifest.evidence_id, content=canonical_json(manifest.model_dump(mode="json")), locator=manifest.path))
    graph_document = next((item for item in normalized_graph.evidence if item.kind == EvidenceKind.GRAPH_DOCUMENT), None)
    if graph_document:
        markers = ("config", "docker", "deploy", "infra", "main", "app", "api", "server", "database", "queue")
        candidates = [
            item for item in normalized_graph.nodes
            if any(marker in " ".join(filter(None, (item.name, item.path, item.node_type))).casefold() for marker in markers)
        ]
        graph_limit = int(os.getenv("C4_GRAPHIFY_CONTEXT_ITEMS", "100"))
        selected_nodes = candidates[:graph_limit]
        selected_ids = {item.id for item in selected_nodes}
        selected_relations = [
            item for item in normalized_graph.relations
            if item.source in selected_ids or item.target in selected_ids
        ][:graph_limit]
        infrastructure_chunks.append(RetrievalChunk(id=graph_document.id, content=canonical_json({
            "graphify_context": {
                "total_nodes": len(normalized_graph.nodes),
                "total_relations": len(normalized_graph.relations),
                "selected_nodes": len(selected_nodes),
                "selected_relations": len(selected_relations),
                "selection_policy": "infrastructure markers, deterministic order",
            },
        }), locator=graph_document.locator))
        node_evidence = {item.id: item for item in normalized_graph.evidence if item.kind == EvidenceKind.GRAPH_NODE}
        relation_evidence = {item.id: item for item in normalized_graph.evidence if item.kind == EvidenceKind.GRAPH_RELATION}
        infrastructure_chunks.extend(
            RetrievalChunk(id=item.evidence_id, content=canonical_json(item.model_dump(mode="json")), locator=node_evidence[item.evidence_id].locator)
            for item in selected_nodes
        )
        infrastructure_chunks.extend(
            RetrievalChunk(id=item.evidence_id, content=canonical_json(item.model_dump(mode="json")), locator=relation_evidence[item.evidence_id].locator)
            for item in selected_relations
        )
    analyst_evidence = next(item for item in extraction.evidence if item.source == EvidenceSource.ANALYST)
    root_payload = [{"id": item.id, "name": item.name, "kind": item.kind.value} for item in analyst_elements]
    infrastructure_chunks.append(RetrievalChunk(id=analyst_evidence.id, content=canonical_json({"analyst_roots": root_payload}), locator="analyst-context"))
    infrastructure_references = tuple({
        "local_id": item.id,
        "semantic_key": item.id,
        "name": item.name,
        "kind": item.kind.value,
    } for item in analyst_elements)

    if provider == "ollama":
        model = os.getenv("C4_OLLAMA_MODEL", "qwen3:8b")
        infrastructure_agent = infrastructure_agent or OllamaC4Agent(AgentRole.INFRASTRUCTURE, model=model)
        module_agent_factory = module_agent_factory or (
            lambda module_id: OllamaC4Agent(AgentRole.MODULE, module_id, model=model)
        )
        if capability_consolidator is None and consolidator_enabled and not custom_analysis_agents:
            capability_consolidator = OllamaCapabilityConsolidator(
                model=os.getenv("C4_CAPABILITY_CONSOLIDATOR_MODEL", model)
            )
        max_concurrency = int(os.getenv("C4_OLLAMA_MAX_CONCURRENCY", "1"))
    else:
        model = os.getenv("C4_GEMINI_MODEL", "gemini-3.6-flash")
        infrastructure_agent = infrastructure_agent or GeminiC4Agent(AgentRole.INFRASTRUCTURE, model=model)
        module_agent_factory = module_agent_factory or (
            lambda module_id: GeminiC4Agent(AgentRole.MODULE, module_id, model=model)
        )
        if capability_consolidator is None and consolidator_enabled and not custom_analysis_agents:
            capability_consolidator = GeminiCapabilityConsolidator(
                model=os.getenv("C4_CAPABILITY_CONSOLIDATOR_MODEL", model)
            )
        max_concurrency = int(os.getenv("C4_AGENT_MAX_CONCURRENCY", "4"))
    audit_rows = {None: _agent_row(admin, run_id, index_id, "infrastructure", None, model)}
    for module in modules:
        audit_rows[module.module_id] = _agent_row(admin, run_id, index_id, "module", module.module_id, model)

    audit_lock = Lock()

    def retrieve(query: str, module_id: str | None, limit: int):
        checkpoint()
        started = time.monotonic()
        fetch_limit = min(1000, max(limit, limit * int(os.getenv("C4_RETRIEVAL_OVERSAMPLE", "4"))))
        try:
            result = index.retrieve(query, tenant_id=tenant_id, repository_id=repository_id, source_hash=source_hash, limit=fetch_limit)
        except Exception as error:
            checkpoint()
            with audit_lock:
                _insert(admin, "consultas_rag", {
                "ejecucion_c4_id": run_id,
                "ejecucion_agente_id": audit_rows[module_id]["id"],
                "indice_conocimiento_id": index_id,
                "tipo": "semantica",
                "estado": "fallido",
                "consulta_sha256": stable_hash(query),
                "top_k": limit,
                "cantidad_resultados": 0,
                "duracion_ms": int((time.monotonic() - started) * 1000),
                "metadata": {"module_id": module_id},
                "error_ultimo": type(error).__name__,
                "finished_at": _now(),
                })
            raise
        scoped_hits = [item for item in result.hits if _hit_in_agent_scope(item.source_path, module_id)]
        hits = scoped_hits[:limit]
        rejected_scope = len(result.hits) - len(scoped_hits)
        ids = [item.chunk_id for item in hits]
        checkpoint()
        with audit_lock:
            _insert(admin, "consultas_rag", {
            "ejecucion_c4_id": run_id,
            "ejecucion_agente_id": audit_rows[module_id]["id"],
            "indice_conocimiento_id": index_id,
            "tipo": "semantica",
            "estado": "completado",
            "consulta_sha256": stable_hash(query),
            "resultados_sha256": stable_hash([{"id": item.chunk_id, "hash": item.chunk_hash} for item in hits]),
            "top_k": limit,
            "cantidad_resultados": len(hits),
            "duracion_ms": int((time.monotonic() - started) * 1000),
            "metadata": {
                "module_id": module_id,
                "chunk_ids": ids,
                "rejected_unknown": result.audit.rejected_unknown,
                "rejected_stale": result.audit.rejected_stale,
                "rejected_scope": rejected_scope,
            },
            "finished_at": _now(),
            })
        return tuple(RetrievalChunk(id=item.chunk_id, content=item.content, locator=item.source_path) for item in hits)

    orchestrator = AgentOrchestrator(
        infrastructure_agent,
        module_agent_factory,
        retrieve,
        max_concurrency=max_concurrency,
        max_retrieval_queries=max_queries_per_agent,
        max_chunks_per_query=int(os.getenv("C4_AGENT_MAX_CHUNKS_PER_QUERY", "12")),
    )

    def forward_agent_progress(completadas: int, totales: int, modulo: str) -> None:
        checkpoint()
        total_modulos = max(0, totales - 1)
        if modulo == "infrastructure":
            progress("infraestructura", 0, total_modulos)
        else:
            progress(modulo, completadas - 1, total_modulos)

    try:
        fragments = orchestrator.run(
            modules,
            infrastructure_chunks=tuple(infrastructure_chunks),
            infrastructure_references=infrastructure_references,
            heartbeat=forward_agent_progress,
        )
    except Exception as error:
        for row in audit_rows.values():
            _update(admin, "ejecuciones_agente", row["id"], {"estado": "fallido", "error_ultimo": type(error).__name__, "finished_at": _now()})
        raise
    checkpoint()

    agents_dir = run_root / "agents"
    fragment_paths: list[Path] = []
    for fragment in fragments:
        checkpoint()
        path = agents_dir / f"{stable_id('fragment_artifact', fragment.fragment_id)}.json"
        _write_atomic(path, fragment.model_dump(mode="json"))
        fragment_paths.append(path)
        row = audit_rows[fragment.metadata.module_id]
        _update(admin, "ejecuciones_agente", row["id"], {
            "estado": "completado",
            "entrada_sha256": stable_hash({
                "module_id": fragment.metadata.module_id,
                "available_ids": sorted(
                    item.id for item in infrastructure_chunks
                    if fragment.metadata.module_id is None
                ) if fragment.metadata.module_id is None else sorted(item.id for item in modules_by_id[fragment.metadata.module_id])
            }),
            "salida_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "modelo": fragment.metadata.model,
            "finished_at": _now(),
        })

    references = {item.id: item.id for item in analyst_elements}
    system = next(item for item in analyst_elements if item.kind.value == "software_system")
    references.update({"root": system.id, "analyst-root": system.id, "software-system": system.id})
    merge_input_hash = stable_hash([item.model_dump(mode="json") for item in fragments])
    merge_row = _insert(admin, "ejecuciones_agente", {
        "ejecucion_c4_id": run_id, "indice_conocimiento_id": index_id, "tipo": "fusionador", "estado": "procesando",
        "entrada_sha256": merge_input_hash, "modelo": "deterministic", "version_prompt": "merge-v1", "metadata": {}, "started_at": _now(),
    })
    try:
        merged = merge_agent_graphs(fragments, existing_references=references)
    except Exception as error:
        _update(admin, "ejecuciones_agente", merge_row["id"], {
            "estado": "fallido",
            "error_ultimo": type(error).__name__,
            "finished_at": _now(),
        })
        raise
    merged = merged.model_copy(update={
        "elements": tuple(_reconcile_semantic_components(list(merged.elements))),
    })
    merge_dir = run_root / "merge"
    consolidation_path = merge_dir / "capability-consolidation.json"
    repair_manifest_path = merge_dir / "capability-repair.json"
    consolidation_paths: list[Path] = []
    consolidation_groups = []
    repair_iterations = []
    maximum_repair_iterations = min(3, max(1, int(os.getenv("C4_CAPABILITY_REPAIR_ITERATIONS", "2"))))
    initial_component_count = sum(item.kind == ElementKind.COMPONENT for item in merged.elements)
    repair_stabilized = capability_consolidator is None or initial_component_count <= 1
    if capability_consolidator is not None and initial_component_count > 1:
        for iteration in range(1, maximum_repair_iterations + 1):
            checkpoint()
            iteration_input_hash = stable_hash(merged.model_dump(mode="json"))
            consolidation_row = _insert(admin, "ejecuciones_agente", {
                "ejecucion_c4_id": run_id,
                "indice_conocimiento_id": index_id,
                "tipo": "fusionador",
                "estado": "procesando",
                "entrada_sha256": iteration_input_hash,
                "modelo": capability_consolidator.model,
                "version_prompt": CONSOLIDATION_PROMPT_VERSION,
                "metadata": {"stage": "capability_consolidation", "iteration": iteration},
                "started_at": _now(),
            })
            try:
                iteration_plan = capability_consolidator.consolidate(merged)
                repaired = apply_consolidation_plan(merged, iteration_plan)
                iteration_output_hash = stable_hash(repaired.model_dump(mode="json"))
                iteration_path = merge_dir / f"capability-consolidation-{iteration:02d}.json"
                iteration_payload = {
                    "iteration": iteration,
                    "input_sha256": iteration_input_hash,
                    "output_sha256": iteration_output_hash,
                    "groups": [item.model_dump(mode="json") for item in iteration_plan.groups],
                }
                _write_atomic(iteration_path, iteration_payload)
                iteration_hash = hashlib.sha256(iteration_path.read_bytes()).hexdigest()
                consolidation_paths.append(iteration_path)
                repair_iterations.append(iteration_payload)
                consolidation_groups.extend(iteration_plan.groups)
                _update(admin, "ejecuciones_agente", consolidation_row["id"], {
                    "estado": "completado",
                    "salida_sha256": iteration_hash,
                    "finished_at": _now(),
                })
                high_confidence_groups = sum(
                    item.confidence == "high" for item in iteration_plan.groups
                )
                _insert(admin, "evaluaciones_c4", {
                    "ejecucion_c4_id": run_id,
                    "ejecucion_agente_id": consolidation_row["id"],
                    "tipo": "fusion",
                    "estado": "completado",
                    "entrada_sha256": iteration_input_hash,
                    "reporte_sha256": iteration_hash,
                    "metadata": {
                        "stage": "capability_consolidation",
                        "iteration": iteration,
                        "group_count": len(iteration_plan.groups),
                        "high_confidence_group_count": high_confidence_groups,
                    },
                    "finished_at": _now(),
                })
            except Exception as error:
                _update(admin, "ejecuciones_agente", consolidation_row["id"], {
                    "estado": "fallido",
                    "error_ultimo": type(error).__name__,
                    "finished_at": _now(),
                })
                raise
            previous_element_ids = {item.id for item in merged.elements}
            merged = repaired
            remaining_components = sum(item.kind == ElementKind.COMPONENT for item in merged.elements)
            if (
                not high_confidence_groups
                or remaining_components <= 1
                or {item.id for item in merged.elements} == previous_element_ids
            ):
                repair_stabilized = True
                break
    consolidation_plan = CapabilityConsolidationPlan(groups=tuple(consolidation_groups))
    _write_atomic(consolidation_path, consolidation_plan.model_dump(mode="json"))
    _write_atomic(repair_manifest_path, {
        "configured_max_iterations": maximum_repair_iterations,
        "completed_iterations": len(repair_iterations),
        "stabilized": repair_stabilized,
        "iterations": repair_iterations,
    })
    merged = _augment_architecture_graph(merged, chunks, modules, system.id, system.name)
    _validate_architecture_quality(merged)
    checkpoint()
    merged_path = merge_dir / "merged-graph.json"
    conflicts_path = merge_dir / "conflicts.json"
    orphans_path = merge_dir / "orphans.json"
    _write_atomic(merged_path, merged.model_dump(mode="json"))
    _write_atomic(conflicts_path, [item.model_dump(mode="json") for item in merged.conflicts])
    _write_atomic(orphans_path, [item.model_dump(mode="json") for item in merged.orphans])
    merged_hash = hashlib.sha256(merged_path.read_bytes()).hexdigest()
    _update(admin, "ejecuciones_agente", merge_row["id"], {"estado": "completado", "salida_sha256": merged_hash, "finished_at": _now()})
    _insert(admin, "evaluaciones_c4", {
        "ejecucion_c4_id": run_id, "ejecucion_agente_id": merge_row["id"], "tipo": "fusion", "estado": "completado",
        "entrada_sha256": merge_input_hash, "reporte_sha256": merged_hash,
        "metadata": {"conflict_ids": [item.id for item in merged.conflicts], "orphan_ids": [item.id for item in merged.orphans]}, "finished_at": _now(),
    })

    judge_entries: list[tuple[JudgeReport, dict[str, Any] | None]] = [(deterministic_judge_report(merged), None)]
    if os.getenv("C4_ENABLE_LLM_JUDGE", "false").casefold() == "true":
        llm_row = _insert(admin, "ejecuciones_agente", {
            "ejecucion_c4_id": run_id, "indice_conocimiento_id": index_id, "tipo": "juez", "estado": "procesando",
            "entrada_sha256": merged_hash, "modelo": model, "version_prompt": "judge-v1", "metadata": {"advisory_only": True}, "started_at": _now(),
        })
        try:
            judge = OllamaAdvisoryJudge(model=model) if provider == "ollama" else GeminiAdvisoryJudge(model=model)
            judge_entries.append((judge.evaluate(merged), llm_row))
        except Exception as error:
            _update(admin, "ejecuciones_agente", llm_row["id"], {"estado": "fallido", "error_ultimo": type(error).__name__, "finished_at": _now()})
            raise
    evaluation_dir = run_root / "evaluation"
    judge_paths: list[Path] = []
    for report, existing_row in judge_entries:
        checkpoint()
        judge_row = existing_row or _insert(admin, "ejecuciones_agente", {
            "ejecucion_c4_id": run_id, "indice_conocimiento_id": index_id, "tipo": "juez", "estado": "procesando",
            "entrada_sha256": merged_hash, "modelo": report.judge, "version_prompt": "judge-v1", "metadata": {}, "started_at": _now(),
        })
        path = evaluation_dir / f"{stable_id('judge_artifact', report.judge)}.json"
        _write_atomic(path, report.model_dump(mode="json"))
        report_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        _update(admin, "ejecuciones_agente", judge_row["id"], {"estado": "completado", "salida_sha256": report_hash, "finished_at": _now()})
        verdict = "requiere_revision" if report.findings else "aprobado"
        _insert(admin, "evaluaciones_c4", {
            "ejecucion_c4_id": run_id, "ejecucion_agente_id": judge_row["id"], "tipo": "juez", "estado": "completado",
            "entrada_sha256": merged_hash, "reporte_sha256": report_hash, "veredicto": verdict,
            "metadata": {"finding_ids": [item.id for item in report.findings], "advisory_only": True}, "finished_at": _now(),
        })
        judge_paths.append(path)

    elements, relationships = to_c4core_candidates(merged)
    agent_evidence = tuple(_evidence(EvidenceSource.AGENT, EvidenceKind.AGENT_OUTPUT, path.relative_to(run_root).as_posix(), {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "artifact": path.relative_to(run_root).as_posix()
    }) for path in (
        *fragment_paths, *consolidation_paths, consolidation_path, repair_manifest_path,
        merged_path, conflicts_path, orphans_path, *judge_paths,
    ))
    chunk_by_id = {item.id: item for item in chunks}
    extraction_evidence_by_id = {item.id: item for item in extraction.evidence}
    merged_by_id = {item.id: item for item in merged.elements}
    merged_relationship_by_id = {item.id: item for item in merged.relationships}
    citation_agents: dict[str, set[str]] = {}
    citation_modules: dict[str, set[str]] = {}
    for fragment in fragments:
        for item in (*fragment.elements, *fragment.relationships):
            for evidence_id in item.evidence_chunk_ids:
                citation_agents.setdefault(evidence_id, set()).add(fragment.metadata.agent_id)
                if fragment.metadata.module_id:
                    citation_modules.setdefault(evidence_id, set()).add(fragment.metadata.module_id)

    def metadata_for_candidate(candidate):
        merged_item = merged_by_id.get(candidate.id) or merged_relationship_by_id.get(candidate.id)
        evidence_ids = tuple(merged_item.evidence_chunk_ids) if merged_item else tuple(candidate.evidence_ids)
        agents = (
            set(merged_item.agent_ids)
            if candidate.id in merged_by_id
            else {agent for evidence_id in evidence_ids for agent in citation_agents.get(evidence_id, set())}
        )
        modules_for_candidate = (
            set(merged_item.module_ids)
            if candidate.id in merged_by_id
            else {module for evidence_id in evidence_ids for module in citation_modules.get(evidence_id, set())}
        )
        marcado = None
        if (
            merged_item is not None
            and getattr(merged_item, "tags", None)
            and "sin_evidencia_import" in merged_item.tags
        ):
            marcado = "sin_evidencia_import"
        return {
            "agente": ", ".join(sorted(agents)),
            "modulo": ", ".join(sorted(modules_for_candidate)),
            "marcado": marcado,
            "evidencias": [
                {
                    "id": evidence_id,
                    "ruta": chunk_by_id[evidence_id].source_path,
                    "linea_inicio": chunk_by_id[evidence_id].symbol.start_line,
                    "linea_fin": chunk_by_id[evidence_id].symbol.end_line,
                    "simbolo": chunk_by_id[evidence_id].symbol.qualified_name,
                    "agente": ", ".join(sorted(citation_agents.get(evidence_id, set()))),
                    "modulo": ", ".join(sorted(citation_modules.get(evidence_id, set()))),
                } if evidence_id in chunk_by_id else {
                    "id": evidence_id,
                    "ruta": extraction_evidence_by_id[evidence_id].locator,
                    "agente": ", ".join(sorted(citation_agents.get(evidence_id, set()))),
                    "modulo": ", ".join(sorted(citation_modules.get(evidence_id, set()))),
                }
                for evidence_id in evidence_ids
                if evidence_id in chunk_by_id or evidence_id in extraction_evidence_by_id
            ],
        }
    candidate_metadata = {
        candidate.id: metadata_for_candidate(candidate)
        for candidate in (*elements, *relationships)
    }
    metadata = {
        "resumen_evidencia": [{"id": item.id, "ubicacion": item.locator, "hash": item.content_hash} for item in (*semantic_evidence, index_evidence)],
        "agentes": [{"fragmento_id": item.fragment_id, "rol": item.metadata.role.value, "modulo_id": item.metadata.module_id, "modelo": item.metadata.model} for item in fragments],
        "consolidacion_capacidades": [item.model_dump(mode="json") for item in consolidation_plan.groups],
        "reparacion_capacidades": {
            "iteraciones": len(repair_iterations),
            "maximo_iteraciones": maximum_repair_iterations,
            "estabilizada": repair_stabilized,
        },
        "candidatos_metadata": candidate_metadata,
        "conflictos": [{
            "id": item.id,
            "identidad": item.identity,
            "tipo": item.kind.value,
            "razon": item.reason,
            "candidatos_ids": list(item.candidate_ids),
            "valores": list(item.values),
            "evidencia_ids": list(item.evidence_chunk_ids),
        } for item in merged.conflicts],
        "huerfanos": [{
            "id": item.id,
            "tipo_candidato": item.candidate_kind,
            "candidato_id": item.candidate_id,
            "razon": item.reason,
            "referencias_faltantes": list(item.missing_references),
            "evidencia_ids": list(item.evidence_chunk_ids),
        } for item in merged.orphans],
        "hallazgos_juez": [{
            "id": item.id,
            "severidad": item.severity.value,
            "codigo": item.code,
            "mensaje": item.message,
            "elementos_ids": list(item.element_ids),
            "evidencia_ids": list(item.evidence_chunk_ids),
        } for report, _row in judge_entries for item in report.findings],
        "resumen_semantico": {
            "archivos": len({item.source_path for item in chunks}),
            "chunks_totales": len(chunks),
            "chunks_indexados": len(chunks),
            "modulos": len(modules),
            "lenguajes": sorted({item.language.value for item in chunks}),
            "backend_indice": index.health().backend,
        },
    }
    return SemanticAgentResult(
        elements=elements,
        relationships=relationships,
        evidence=(*semantic_evidence, index_evidence, *agent_evidence),
        metadata=metadata,
        artifact_paths=(
            *semantic_paths, *fragment_paths, *consolidation_paths, consolidation_path, repair_manifest_path,
            merged_path, conflicts_path, orphans_path, *judge_paths,
        ),
    )
