"""Tests for canonical hashing."""

import json

from gokart.config.hashing import canonical_json, content_hash


def test_hash_stable_across_key_order() -> None:
    a = {"b": 2, "a": 1, "nested": {"z": 3, "y": 2.0000000001}}
    b = {"nested": {"y": 2.0, "z": 3}, "a": 1, "b": 2}
    assert content_hash(a) == content_hash(b)


def test_hash_excludes_content_hash_field() -> None:
    base = {"id": "motor", "value": 1.0}
    with_hash = {**base, "content_hash": "deadbeef"}
    assert content_hash(base) == content_hash(with_hash)


def test_canonical_json_sorted() -> None:
    payload = canonical_json({"b": 1, "a": 2})
    assert payload == json.dumps({"a": 2, "b": 1}, sort_keys=True, separators=(",", ":"))
