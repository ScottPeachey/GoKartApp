"""Canonical JSON serialization and content hashing."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _normalize_value(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 9)
    if isinstance(value, dict):
        return {key: _normalize_value(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    return value


def to_canonical_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Return a copy suitable for stable hashing (sorted keys, normalized floats)."""
    cleaned = {key: value for key, value in data.items() if key != "content_hash"}
    return _normalize_value(cleaned)


def canonical_json(data: dict[str, Any]) -> str:
    """Serialize configuration data to canonical JSON for hashing."""
    return json.dumps(to_canonical_dict(data), sort_keys=True, separators=(",", ":"))


def content_hash(data: dict[str, Any]) -> str:
    """Compute SHA-256 content hash over canonical JSON."""
    payload = canonical_json(data)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
