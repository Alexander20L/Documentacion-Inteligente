from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel


def canonicalize(value: Any) -> Any:
    """Convert supported values to a stable, JSON-compatible representation."""
    if isinstance(value, BaseModel):
        return canonicalize(value.model_dump(mode="python"))
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return canonicalize(dataclasses.asdict(value))
    if isinstance(value, Enum):
        return canonicalize(value.value)
    if isinstance(value, dict):
        return {
            str(key): canonicalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [canonicalize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        normalized = [canonicalize(item) for item in value]
        return sorted(normalized, key=canonical_json)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Decimal):
        return str(value.normalize())
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Canonical JSON does not support non-finite floats")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Unsupported canonical value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        canonicalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def stable_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def stable_id(namespace: str, *parts: Any, length: int = 20) -> str:
    if not namespace or not namespace.replace("_", "").isalnum():
        raise ValueError("namespace must contain only letters, numbers, and underscores")
    if not 8 <= length <= 64:
        raise ValueError("length must be between 8 and 64")
    digest = stable_hash(list(parts))[:length]
    return f"{namespace}_{digest}"


def deduplicate_stably(values: Iterable[Any]) -> tuple[Any, ...]:
    by_hash = {stable_hash(value): value for value in values}
    return tuple(by_hash[key] for key in sorted(by_hash))
