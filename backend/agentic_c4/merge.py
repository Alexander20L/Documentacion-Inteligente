from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable, Mapping

from c4core import ElementKind, stable_id

from .models import (
    AgentGraphFragment,
    ConflictKind,
    FragmentElement,
    FragmentRelationship,
    MergeConflict,
    MergedAgentGraph,
    MergedElement,
    MergedRelationship,
    OrphanCandidate,
)


def _norm(value: str | None) -> str:
    return " ".join((value or "").strip().casefold().split())


def _identity(element: FragmentElement, default_module: str | None) -> str:
    if element.semantic_key:
        return f"semantic:{_norm(element.semantic_key)}"
    if element.qualified_symbol:
        return f"symbol:{_norm(element.qualified_symbol)}"
    if element.path:
        path = PurePosixPath(element.path.replace("\\", "/")).as_posix().casefold()
        return f"path:{path}|module:{_norm(element.module or default_module)}"
    return f"local:{_norm(element.module or default_module)}:{_norm(element.local_id)}:{element.kind.value}"


@dataclass(frozen=True)
class _SourceElement:
    fragment: AgentGraphFragment
    element: FragmentElement
    identity: str


def merge_agent_graphs(
    fragments: Iterable[AgentGraphFragment],
    *,
    existing_references: Mapping[str, str] | None = None,
) -> MergedAgentGraph:
    """Merge inferred fragments while resolving declared analyst roots externally.

    Existing references participate in endpoint resolution but are never emitted as
    inferred merged elements.
    """
    ordered_fragments = tuple(sorted(fragments, key=lambda item: item.fragment_id))
    if len({item.fragment_id for item in ordered_fragments}) != len(ordered_fragments):
        raise ValueError("fragment IDs must be unique")
    groups: dict[str, list[_SourceElement]] = defaultdict(list)
    for fragment in ordered_fragments:
        for element in fragment.elements:
            identity = _identity(element, fragment.metadata.module_id)
            groups[identity].append(_SourceElement(fragment, element, identity))

    group_ids = {identity: stable_id("agent_element", identity) for identity in groups}
    aliases: dict[str, set[str]] = defaultdict(set)
    external = {_norm(alias): element_id for alias, element_id in (existing_references or {}).items()}
    for identity, sources in groups.items():
        for source in sources:
            element = source.element
            scoped = f"{source.fragment.fragment_id}:{element.local_id}"
            for alias in (scoped, element.local_id, element.semantic_key, element.qualified_symbol, element.path):
                if alias:
                    aliases[_norm(alias)].add(identity)

    conflicts: list[MergeConflict] = []
    rejected: set[str] = set()

    def add_conflict(identity: str, kind: ConflictKind, values: set[str], sources: list[_SourceElement]) -> None:
        rejected.add(identity)
        conflicts.append(MergeConflict(
            id=stable_id("agent_conflict", identity, kind.value),
            identity=identity,
            kind=kind,
            candidate_ids=tuple(sorted(f"{item.fragment.fragment_id}:{item.element.local_id}" for item in sources)),
            values=tuple(sorted(values)),
            evidence_chunk_ids=tuple(sorted({ev for item in sources for ev in item.element.evidence_chunk_ids})),
            reason=f"Incompatible {kind.value} values for stable identity {identity}",
        ))

    for identity in sorted(groups):
        sources = groups[identity]
        kinds = {item.element.kind.value for item in sources}
        technologies = {_norm(item.element.technology) for item in sources if item.element.technology}
        if len(kinds) > 1:
            add_conflict(identity, ConflictKind.TYPE, kinds, sources)
        if len(technologies) > 1:
            add_conflict(identity, ConflictKind.TECHNOLOGY, technologies, sources)

    def resolve(reference: str, fragment_id: str) -> str | None:
        scoped = aliases.get(_norm(f"{fragment_id}:{reference}"), set())
        if len(scoped) == 1:
            return next(iter(scoped))
        matches = aliases.get(_norm(reference), set())
        if len(matches) == 1:
            return next(iter(matches))
        external_id = external.get(_norm(reference))
        return f"external:{external_id}" if external_id else None

    def resolve_parent(source: _SourceElement) -> str | None:
        reference = source.element.parent_ref or ""
        if source.element.kind == ElementKind.CONTAINER:
            external_id = external.get(_norm(reference))
            if external_id:
                return f"external:{external_id}"
        if source.element.kind == ElementKind.COMPONENT:
            candidates = set(aliases.get(_norm(f"{source.fragment.fragment_id}:{reference}"), set()))
            candidates.update(aliases.get(_norm(reference), set()))
            containers = {
                identity
                for identity in candidates
                if any(item.element.kind == ElementKind.CONTAINER for item in groups[identity])
            }
            if len(containers) == 1:
                return next(iter(containers))
        return resolve(reference, source.fragment.fragment_id)

    resolved_parents: dict[str, str | None] = {}
    orphans: list[OrphanCandidate] = []
    for identity in sorted(groups):
        if identity in rejected:
            continue
        sources = groups[identity]
        parents: set[str] = set()
        missing: set[str] = set()
        for source in sources:
            if source.element.parent_ref:
                parent = resolve_parent(source)
                if parent is None or parent in rejected:
                    missing.add(source.element.parent_ref)
                else:
                    parents.add(parent)
        if missing:
            rejected.add(identity)
            orphans.append(_element_orphan(identity, sources, f"Unresolved or quarantined parent: {', '.join(sorted(missing))}", missing))
        elif len(parents) > 1:
            add_conflict(identity, ConflictKind.PARENT, parents, sources)
        else:
            resolved_parents[identity] = next(iter(parents), None)

    # A parent may have become quarantined later in deterministic parent processing.
    changed = True
    while changed:
        changed = False
        for identity, parent in tuple(resolved_parents.items()):
            if identity not in rejected and parent in rejected:
                rejected.add(identity)
                sources = groups[identity]
                orphans.append(_element_orphan(identity, sources, "Parent candidate was quarantined", {parent or ""}))
                changed = True

    merged_elements: list[MergedElement] = []
    for identity in sorted(groups):
        if identity in rejected:
            continue
        sources = groups[identity]
        representative = sorted(sources, key=lambda item: (item.fragment.fragment_id, item.element.local_id))[0].element
        merged_elements.append(MergedElement(
            id=group_ids[identity],
            identity=identity,
            kind=ElementKind(representative.kind.value),
            name=representative.name,
            description=representative.description,
            technology=representative.technology,
            parent_id=(
                resolved_parents[identity].removeprefix("external:")
                if resolved_parents[identity] and resolved_parents[identity].startswith("external:")
                else group_ids[resolved_parents[identity]] if resolved_parents[identity] else None
            ),
            evidence_chunk_ids=tuple(sorted({ev for item in sources for ev in item.element.evidence_chunk_ids})),
            agent_ids=tuple(sorted({item.fragment.metadata.agent_id for item in sources})),
            module_ids=tuple(sorted({item.fragment.metadata.module_id for item in sources if item.fragment.metadata.module_id})),
            models=tuple(sorted({item.fragment.metadata.model for item in sources})),
        ))

    relation_groups: dict[tuple[str, str, str], list[tuple[AgentGraphFragment, FragmentRelationship]]] = defaultdict(list)
    for fragment in ordered_fragments:
        for relation in fragment.relationships:
            source = resolve(relation.source_ref, fragment.fragment_id)
            target = resolve(relation.target_ref, fragment.fragment_id)
            missing = tuple(ref for ref, value in ((relation.source_ref, source), (relation.target_ref, target)) if value is None or value in rejected)
            if missing:
                orphans.append(OrphanCandidate(
                    id=stable_id("agent_orphan", fragment.fragment_id, relation.local_id),
                    candidate_kind="relationship",
                    candidate_id=f"{fragment.fragment_id}:{relation.local_id}",
                    reason="Relationship endpoint is unresolved or quarantined",
                    missing_references=tuple(sorted(set(missing))),
                    evidence_chunk_ids=tuple(sorted(set(relation.evidence_chunk_ids))),
                ))
                continue
            if source == target:
                orphans.append(OrphanCandidate(
                    id=stable_id("agent_orphan", fragment.fragment_id, relation.local_id, "self"),
                    candidate_kind="relationship",
                    candidate_id=f"{fragment.fragment_id}:{relation.local_id}",
                    reason="Self relationship is not a valid C4 candidate",
                    evidence_chunk_ids=tuple(sorted(set(relation.evidence_chunk_ids))),
                ))
                continue
            key = (source or "", target or "", _norm(relation.description))
            relation_groups[key].append((fragment, relation))

    merged_relationships: list[MergedRelationship] = []
    for key in sorted(relation_groups):
        source, target, _description = key
        entries = relation_groups[key]
        technologies = {_norm(relation.technology) for _fragment, relation in entries if relation.technology}
        if len(technologies) > 1:
            identity = "relationship:" + "|".join(key)
            conflicts.append(MergeConflict(
                id=stable_id("agent_conflict", identity, ConflictKind.TECHNOLOGY.value),
                identity=identity,
                kind=ConflictKind.TECHNOLOGY,
                candidate_ids=tuple(sorted(f"{fragment.fragment_id}:{relation.local_id}" for fragment, relation in entries)),
                values=tuple(sorted(technologies)),
                evidence_chunk_ids=tuple(sorted({ev for _fragment, relation in entries for ev in relation.evidence_chunk_ids})),
                reason=f"Incompatible technology values for stable identity {identity}",
            ))
            continue
        representative = sorted(entries, key=lambda item: (item[0].fragment_id, item[1].local_id))[0][1]
        merged_relationships.append(MergedRelationship(
            id=stable_id("agent_relationship", *key, next(iter(technologies), "")),
            source_id=source.removeprefix("external:") if source.startswith("external:") else group_ids[source],
            target_id=target.removeprefix("external:") if target.startswith("external:") else group_ids[target],
            description=representative.description,
            technology=representative.technology,
            evidence_chunk_ids=tuple(sorted({ev for _fragment, relation in entries for ev in relation.evidence_chunk_ids})),
        ))

    for fragment in ordered_fragments:
        for reference in fragment.unresolved_references:
            orphans.append(OrphanCandidate(
                id=stable_id("agent_orphan_reference", fragment.fragment_id, reference.owner_local_id, reference.field, reference.reference),
                candidate_kind="reference",
                candidate_id=f"{fragment.fragment_id}:{reference.owner_local_id}",
                reason=reference.reason,
                missing_references=(reference.reference,),
                evidence_chunk_ids=tuple(sorted(set(reference.evidence_chunk_ids))),
            ))

    return MergedAgentGraph(
        elements=tuple(merged_elements),
        relationships=tuple(merged_relationships),
        conflicts=tuple(sorted(conflicts, key=lambda item: item.id)),
        orphans=tuple(sorted(orphans, key=lambda item: item.id)),
    )


def _element_orphan(identity: str, sources: list[_SourceElement], reason: str, missing: set[str]) -> OrphanCandidate:
    return OrphanCandidate(
        id=stable_id("agent_orphan_element", identity),
        candidate_kind="element",
        candidate_id=identity,
        reason=reason,
        missing_references=tuple(sorted(missing)),
        evidence_chunk_ids=tuple(sorted({ev for item in sources for ev in item.element.evidence_chunk_ids})),
    )
