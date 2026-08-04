from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from .identity import stable_chunk_hash
from .index import KnowledgeIndex, _validate_chunk
from .models import IndexHealth, RetrievalAudit, RetrievalHit, RetrievalResult, SemanticChunk


DIFY_MAX_QUERY_CHARS = 250


class DifyAPIError(RuntimeError):
    pass


@dataclass(frozen=True)
class DifyConfig:
    base_url: str
    api_key: str
    timeout_seconds: float = 30.0
    max_segment_tokens: int = 4000
    mapping_path: str | None = None

    @classmethod
    def from_env(cls) -> "DifyConfig":
        base_url = os.environ.get("DIFY_BASE_URL", "").strip()
        api_key = os.environ.get("DIFY_API_KEY", "").strip()
        if not base_url or not api_key:
            raise ValueError("DIFY_BASE_URL and DIFY_API_KEY are required")
        return cls(
            base_url=base_url,
            api_key=api_key,
            timeout_seconds=float(os.environ.get("DIFY_TIMEOUT_SECONDS", "30")),
            mapping_path=os.environ.get("DIFY_MAPPING_PATH") or None,
        )


class DifyKnowledgeIndex(KnowledgeIndex):
    """Adapter for the Dify Knowledge API as exposed by Dify 1.x.

    Each semantic chunk is a separate Dify document. The in-process mapping remains
    authoritative; API keys are only held in memory and are never included in payloads.
    """

    def __init__(self, config: DifyConfig) -> None:
        self.config = config
        self._datasets: dict[tuple[str, str, str], str] = {}
        self._chunks: dict[tuple[str, str], SemanticChunk] = {}
        self._document_refs: dict[tuple[str, str], tuple[str, str]] = {}
        self._load_mapping()

    def _load_mapping(self) -> None:
        if not self.config.mapping_path:
            return
        path = Path(self.config.mapping_path)
        if not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._datasets = {tuple(item["scope"]): item["dataset_id"] for item in data.get("datasets", [])}
            self._document_refs = {
                (item["dataset_id"], item["chunk_id"]): (item["document_id"], item["chunk_hash"])
                for item in data.get("documents", [])
            }
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise DifyAPIError(f"Invalid Dify mapping file {path}: {exc}") from exc

    def _save_mapping(self) -> None:
        if not self.config.mapping_path:
            return
        path = Path(self.config.mapping_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "datasets": [
                {"scope": list(scope), "dataset_id": dataset_id}
                for scope, dataset_id in sorted(self._datasets.items())
            ],
            "documents": [
                {"dataset_id": dataset_id, "chunk_id": chunk_id, "document_id": ref[0], "chunk_hash": ref[1]}
                for (dataset_id, chunk_id), ref in sorted(self._document_refs.items())
            ],
        }
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        temporary.replace(path)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            f"{self.config.base_url.rstrip('/')}{path}", data=body, method=method,
            headers={"Authorization": f"Bearer {self.config.api_key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            response_body = exc.read(2048).decode("utf-8", errors="replace").strip()
            detail = f"; response: {response_body}" if response_body else ""
            raise DifyAPIError(f"Dify request {method} {path} failed: {exc}{detail}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise DifyAPIError(f"Dify request {method} {path} failed: {exc}") from exc

    @staticmethod
    def _scope(chunk: SemanticChunk) -> tuple[str, str, str]:
        return chunk.tenant_id, chunk.repository_id, chunk.source_hash

    def _dataset(self, scope: tuple[str, str, str]) -> str:
        existing = self._datasets.get(scope)
        if existing:
            return existing
        digest = sha256("\0".join(scope).encode("utf-8")).hexdigest()[:20]
        name = f"semantic-{digest}"
        remote = None
        page = 1
        while remote is None:
            listing = self._request("GET", f"/v1/datasets?page={page}&limit=100")
            rows = listing.get("data", [])
            remote = next((item for item in rows if item.get("name") == name), None)
            if remote is not None or not listing.get("has_more") or not rows:
                break
            page += 1
        response = remote or self._request("POST", "/v1/datasets", {"name": name, "permission": "only_me"})
        dataset_id = response.get("id")
        if not isinstance(dataset_id, str):
            raise DifyAPIError("Dify dataset creation response did not contain an id")
        self._datasets[scope] = dataset_id
        self._save_mapping()
        return dataset_id

    def index_chunks(self, chunks: tuple[SemanticChunk, ...]) -> None:
        if not chunks:
            return
        scope = self._scope(chunks[0])
        if any(self._scope(chunk) != scope for chunk in chunks):
            raise ValueError("A Dify indexing batch must have one tenant/repository/source scope")
        dataset_id = self._dataset(scope)
        remote_documents = self._list_documents_by_name(dataset_id)
        for chunk in chunks:
            _validate_chunk(chunk)
            known_ref = self._document_refs.get((dataset_id, chunk.id))
            if known_ref and known_ref[1] == chunk.chunk_hash:
                self._chunks[(dataset_id, known_ref[0])] = chunk
                continue
            remote_id = known_ref[0] if known_ref else remote_documents.get(chunk.id)
            if remote_id:
                self._request("DELETE", f"/v1/datasets/{dataset_id}/documents/{remote_id}")
                self._chunks.pop((dataset_id, remote_id), None)
                self._document_refs.pop((dataset_id, chunk.id), None)
                self._save_mapping()
            response = self._request(
                "POST",
                f"/v1/datasets/{dataset_id}/document/create-by-text",
                self._document_payload(chunk),
            )
            document = response.get("document", response)
            document_id = document.get("id") if isinstance(document, dict) else None
            if not isinstance(document_id, str):
                raise DifyAPIError("Dify document creation response did not contain a document id")
            self._chunks[(dataset_id, document_id)] = chunk
            self._document_refs[(dataset_id, chunk.id)] = (document_id, chunk.chunk_hash)
            self._save_mapping()

    def _document_payload(self, chunk: SemanticChunk) -> dict[str, Any]:
        return {
            "name": chunk.id,
            "text": chunk.content,
            "indexing_technique": "high_quality",
            "process_rule": {
                "mode": "custom",
                "rules": {
                    "pre_processing_rules": [
                        {"id": "remove_extra_spaces", "enabled": False},
                        {"id": "remove_urls_emails", "enabled": False},
                    ],
                    "segmentation": {"separator": "\u0000", "max_tokens": self.config.max_segment_tokens},
                },
            },
        }

    def _list_documents_by_name(self, dataset_id: str) -> dict[str, str]:
        documents: dict[str, str] = {}
        page = 1
        while True:
            response = self._request(
                "GET",
                f"/v1/datasets/{dataset_id}/documents?page={page}&limit=100",
            )
            rows = response.get("data", [])
            for item in rows:
                if isinstance(item, dict) and isinstance(item.get("name"), str) and isinstance(item.get("id"), str):
                    documents[item["name"]] = item["id"]
            if not response.get("has_more") or not rows:
                return documents
            page += 1

    def dataset_id(self, *, tenant_id: str, repository_id: str, source_hash: str) -> str | None:
        return self._datasets.get((tenant_id, repository_id, source_hash))

    def ensure_dataset(self, *, tenant_id: str, repository_id: str, source_hash: str) -> str:
        return self._dataset((tenant_id, repository_id, source_hash))

    def retrieve(
        self, query: str, *, tenant_id: str, repository_id: str, source_hash: str, limit: int = 10
    ) -> RetrievalResult:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        if len(query) > DIFY_MAX_QUERY_CHARS:
            raise ValueError(f"query must contain at most {DIFY_MAX_QUERY_CHARS} characters")
        scope = (tenant_id, repository_id, source_hash)
        dataset_id = self._datasets.get(scope)
        records: list[Any] = []
        if dataset_id:
            response = self._request("POST", f"/v1/datasets/{dataset_id}/retrieve", {
                "query": query,
                "retrieval_model": {
                    "search_method": "semantic_search",
                    "reranking_enable": False,
                    "top_k": limit,
                    "score_threshold_enabled": False,
                },
            })
            records = response.get("records", [])
        hits: list[RetrievalHit] = []
        rejected_unknown = rejected_stale = 0
        for record in records:
            segment = record.get("segment", {}) if isinstance(record, dict) else {}
            document = segment.get("document", {}) if isinstance(segment, dict) else {}
            document_id = segment.get("document_id") or record.get("document_id") or document.get("id")
            chunk = self._chunks.get((dataset_id, document_id)) if dataset_id and isinstance(document_id, str) else None
            if chunk is None:
                rejected_unknown += 1
                continue
            if self._scope(chunk) != scope or stable_chunk_hash(chunk.id, chunk.content) != chunk.chunk_hash:
                rejected_stale += 1
                continue
            hits.append(RetrievalHit(
                chunk_id=chunk.id, chunk_hash=chunk.chunk_hash, score=float(record.get("score", 0.0)),
                content=chunk.content, source_path=chunk.source_path, qualified_symbol=chunk.symbol.qualified_name,
            ))
        hits = hits[:limit]
        return RetrievalResult(hits=tuple(hits), audit=RetrievalAudit(
            tenant_id=tenant_id, repository_id=repository_id, source_hash=source_hash, query=query,
            requested_limit=limit, accepted_chunk_ids=tuple(hit.chunk_id for hit in hits),
            rejected_unknown=rejected_unknown, rejected_stale=rejected_stale,
        ))

    def delete_index(self, *, tenant_id: str, repository_id: str, source_hash: str) -> None:
        scope = (tenant_id, repository_id, source_hash)
        dataset_id = self._datasets.pop(scope, None)
        if not dataset_id:
            return
        self._request("DELETE", f"/v1/datasets/{dataset_id}")
        self._chunks = {key: chunk for key, chunk in self._chunks.items() if key[0] != dataset_id}
        self._document_refs = {key: ref for key, ref in self._document_refs.items() if key[0] != dataset_id}
        self._save_mapping()

    def health(self) -> IndexHealth:
        try:
            self._request("GET", "/v1/datasets?page=1&limit=1")
            return IndexHealth(healthy=True, backend="dify")
        except DifyAPIError as exc:
            return IndexHealth(healthy=False, backend="dify", detail=str(exc))
