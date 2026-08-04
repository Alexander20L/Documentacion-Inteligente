from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter
import re

from .identity import stable_chunk_hash
from .models import IndexHealth, PublicationPolicy, RetrievalAudit, RetrievalHit, RetrievalResult, SemanticChunk


class KnowledgeIndex(ABC):
    @abstractmethod
    def index_chunks(self, chunks: tuple[SemanticChunk, ...]) -> None:
        raise NotImplementedError

    @abstractmethod
    def retrieve(
        self, query: str, *, tenant_id: str, repository_id: str, source_hash: str, limit: int = 10
    ) -> RetrievalResult:
        raise NotImplementedError

    @abstractmethod
    def delete_index(self, *, tenant_id: str, repository_id: str, source_hash: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def health(self) -> IndexHealth:
        raise NotImplementedError


def _validate_chunk(chunk: SemanticChunk) -> None:
    if chunk.publication_policy == PublicationPolicy.EXCLUDE:
        raise ValueError(f"Chunk {chunk.id} is excluded by publication policy")
    if stable_chunk_hash(chunk.id, chunk.content) != chunk.chunk_hash:
        raise ValueError(f"Chunk {chunk.id} has an invalid or stale content hash")


class InMemoryKnowledgeIndex(KnowledgeIndex):
    def __init__(self) -> None:
        self._chunks: dict[tuple[str, str, str, str], SemanticChunk] = {}

    def index_chunks(self, chunks: tuple[SemanticChunk, ...]) -> None:
        for chunk in chunks:
            _validate_chunk(chunk)
            self._chunks[(chunk.tenant_id, chunk.repository_id, chunk.source_hash, chunk.id)] = chunk

    def retrieve(
        self, query: str, *, tenant_id: str, repository_id: str, source_hash: str, limit: int = 10
    ) -> RetrievalResult:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        query_terms = Counter(re.findall(r"\w+", query.casefold()))
        ranked: list[tuple[float, SemanticChunk]] = []
        rejected_stale = 0
        for chunk in self._chunks.values():
            if (chunk.tenant_id, chunk.repository_id, chunk.source_hash) != (tenant_id, repository_id, source_hash):
                continue
            if stable_chunk_hash(chunk.id, chunk.content) != chunk.chunk_hash:
                rejected_stale += 1
                continue
            terms = Counter(re.findall(r"\w+", chunk.content.casefold()))
            overlap = sum(min(count, terms[term]) for term, count in query_terms.items())
            score = overlap / max(sum(query_terms.values()), 1)
            if score > 0 or not query_terms:
                ranked.append((score, chunk))
        ranked.sort(key=lambda item: (-item[0], item[1].id))
        hits = tuple(
            RetrievalHit(
                chunk_id=chunk.id, chunk_hash=chunk.chunk_hash, score=score, content=chunk.content,
                source_path=chunk.source_path, qualified_symbol=chunk.symbol.qualified_name,
            )
            for score, chunk in ranked[:limit]
        )
        return RetrievalResult(
            hits=hits,
            audit=RetrievalAudit(
                tenant_id=tenant_id, repository_id=repository_id, source_hash=source_hash, query=query,
                requested_limit=limit, accepted_chunk_ids=tuple(hit.chunk_id for hit in hits),
                rejected_stale=rejected_stale,
            ),
        )

    def delete_index(self, *, tenant_id: str, repository_id: str, source_hash: str) -> None:
        self._chunks = {
            key: chunk for key, chunk in self._chunks.items()
            if (chunk.tenant_id, chunk.repository_id, chunk.source_hash) != (tenant_id, repository_id, source_hash)
        }

    def health(self) -> IndexHealth:
        return IndexHealth(healthy=True, backend="memory", detail=f"{len(self._chunks)} chunks")
