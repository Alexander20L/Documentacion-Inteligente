from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Iterable

from .canonical import stable_hash, stable_id
from .models import (
    AnalystContext,
    EvidenceKind,
    EvidenceRecord,
    EvidenceSource,
    ExtractionContext,
    InventoryEntry,
    ManifestRecord,
    NormalizedGraph,
    NormalizedGraphNode,
    NormalizedGraphRelation,
    QuarantinedGraphRelation,
)


class ExtractionAdapter(ABC):
    @abstractmethod
    def extract(self, repository_root: Path, analyst: AnalystContext) -> ExtractionContext:
        """Extract complete, source-grounded evidence without sampling."""


def _evidence(
    source: EvidenceSource,
    kind: EvidenceKind,
    locator: str,
    payload: Any,
) -> EvidenceRecord:
    digest = stable_hash(payload)
    return EvidenceRecord(
        id=stable_id("evidence", source, kind, locator, digest),
        source=source,
        kind=kind,
        locator=locator,
        payload=payload,
        content_hash=digest,
    )


def inventory_repository(repository_root: Path) -> tuple[tuple[InventoryEntry, ...], tuple[EvidenceRecord, ...]]:
    root = repository_root.resolve()
    if not root.is_dir():
        raise ValueError(f"Repository root is not a directory: {repository_root}")
    entries: list[InventoryEntry] = []
    evidence: list[EvidenceRecord] = []
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        data = path.read_bytes()
        entry = InventoryEntry(path=relative, size=len(data), sha256=hashlib.sha256(data).hexdigest())
        entries.append(entry)
        evidence.append(_evidence(EvidenceSource.INVENTORY, EvidenceKind.FILE, relative, entry.model_dump()))
    return tuple(entries), tuple(evidence)


_MANIFEST_NAMES = {
    "package.json": "npm",
    "pyproject.toml": "python",
    "requirements.txt": "python-requirements",
    "pom.xml": "maven",
    "build.gradle": "gradle",
    "build.gradle.kts": "gradle-kotlin",
    "go.mod": "go",
    "cargo.toml": "cargo",
    "composer.json": "composer",
}


def extract_manifests(repository_root: Path, inventory: Iterable[InventoryEntry]) -> tuple[tuple[ManifestRecord, ...], tuple[EvidenceRecord, ...]]:
    root = repository_root.resolve()
    manifests: list[ManifestRecord] = []
    evidence: list[EvidenceRecord] = []
    for entry in sorted(inventory, key=lambda item: item.path):
        manifest_type = _MANIFEST_NAMES.get(Path(entry.path).name.lower())
        if manifest_type is None:
            continue
        path = root / Path(entry.path)
        text = path.read_text(encoding="utf-8", errors="replace")
        data: Any = text
        if path.suffix.lower() == ".json":
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                data = {"invalid_json": True, "raw": text}
        item_evidence = _evidence(EvidenceSource.MANIFEST, EvidenceKind.MANIFEST, entry.path, data)
        evidence.append(item_evidence)
        manifests.append(ManifestRecord(path=entry.path, manifest_type=manifest_type, data=data, evidence_id=item_evidence.id))
    return tuple(manifests), tuple(evidence)


def build_analyst_context(repository_root: Path, analyst: AnalystContext) -> ExtractionContext:
    inventory, inventory_evidence = inventory_repository(repository_root)
    manifests, manifest_evidence = extract_manifests(repository_root, inventory)
    analyst_evidence = _evidence(
        EvidenceSource.ANALYST,
        EvidenceKind.ANALYST_CONTEXT,
        "analyst-context",
        analyst.model_dump(mode="json"),
    )
    return ExtractionContext(
        repository_root=repository_root.resolve().as_posix(),
        analyst=analyst,
        inventory=inventory,
        manifests=manifests,
        evidence=tuple(sorted((*inventory_evidence, *manifest_evidence, analyst_evidence), key=lambda item: item.id)),
    )


class FilesystemExtractionAdapter(ExtractionAdapter):
    def extract(self, repository_root: Path, analyst: AnalystContext) -> ExtractionContext:
        return build_analyst_context(repository_root, analyst)


def _endpoint_id(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("id", "name", "label"):
            endpoint = _endpoint_id(value.get(key))
            if endpoint is not None:
                return endpoint
        return None
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_endpoint(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        endpoint = _endpoint_id(payload.get(key))
        if endpoint is not None:
            return endpoint
    return None


def normalize_graphify_json(graph: dict[str, Any]) -> NormalizedGraph:
    if not isinstance(graph, dict):
        raise TypeError("Graphify document must be an object")
    document_evidence = _evidence(EvidenceSource.GRAPHIFY, EvidenceKind.GRAPH_DOCUMENT, "graph.json", graph)
    raw_nodes = graph.get("nodes", [])
    if not isinstance(raw_nodes, list):
        raw_nodes = []

    nodes: list[NormalizedGraphNode] = []
    evidence: list[EvidenceRecord] = [document_evidence]
    known_ids: set[str] = set()
    for index, raw in enumerate(raw_nodes):
        payload = raw if isinstance(raw, dict) else {"value": raw}
        locator = f"graph.json#/nodes/{index}"
        item_evidence = _evidence(EvidenceSource.GRAPHIFY, EvidenceKind.GRAPH_NODE, locator, payload)
        evidence.append(item_evidence)
        raw_id = _endpoint_id(payload.get("id"))
        node_id = raw_id or stable_id("graph_node", locator, payload)
        name = str(payload.get("name") or payload.get("label") or node_id)
        community = payload["community"] if "community" in payload else payload.get("group")
        nodes.append(NormalizedGraphNode(
            id=node_id,
            name=name,
            node_type=_endpoint_id(payload.get("type") or payload.get("kind")),
            path=_endpoint_id(payload.get("path")),
            community=community,
            evidence_id=item_evidence.id,
        ))
        known_ids.add(node_id)

    relations: list[NormalizedGraphRelation] = []
    quarantined: list[QuarantinedGraphRelation] = []
    for collection in ("links", "edges"):
        raw_relations = graph.get(collection, [])
        if not isinstance(raw_relations, list):
            continue
        for index, raw in enumerate(raw_relations):
            payload = raw if isinstance(raw, dict) else {"value": raw}
            locator = f"graph.json#/{collection}/{index}"
            item_evidence = _evidence(EvidenceSource.GRAPHIFY, EvidenceKind.GRAPH_RELATION, locator, payload)
            evidence.append(item_evidence)
            source = _first_endpoint(payload, ("source", "from", "start", "source_id"))
            target = _first_endpoint(payload, ("target", "to", "end", "target_id"))
            relation = NormalizedGraphRelation(
                id=_endpoint_id(payload.get("id")) or stable_id("graph_relation", collection, index, payload),
                source=source or "",
                target=target or "",
                relation_type=str(payload.get("type") or payload.get("label") or payload.get("relation") or "related_to"),
                collection=collection,
                evidence_id=item_evidence.id,
            )
            missing = [endpoint for endpoint in (source, target) if endpoint not in known_ids]
            if source is None or target is None:
                reason = "missing source or target endpoint"
            elif missing:
                reason = "dangling endpoint(s): " + ", ".join(str(item) for item in missing)
            else:
                relations.append(relation)
                continue
            quarantined.append(QuarantinedGraphRelation(relation=relation, reason=reason))

    return NormalizedGraph(
        nodes=tuple(sorted(nodes, key=lambda item: item.id)),
        relations=tuple(sorted(relations, key=lambda item: item.id)),
        quarantined_relations=tuple(sorted(quarantined, key=lambda item: item.relation.id)),
        evidence=tuple(sorted(evidence, key=lambda item: item.id)),
    )
