from __future__ import annotations

import hashlib
import json


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stable_chunk_id(source_hash: str, source_path: str, qualified_symbol: str, parser_version: str) -> str:
    payload = json.dumps(
        [source_hash, source_path.replace("\\", "/"), qualified_symbol, parser_version],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return "sch_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def stable_chunk_hash(chunk_id: str, content: str) -> str:
    return sha256_text(f"{chunk_id}\0{content}")
