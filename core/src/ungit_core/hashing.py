"""Stable hashing helpers for core objects and file content."""

from __future__ import annotations

import hashlib
import json
from typing import Any


HASH_PREFIX = "sha256:"


def canonical_json(data: Any) -> bytes:
    return json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def content_hash(data: bytes) -> str:
    return HASH_PREFIX + hashlib.sha256(data).hexdigest()


def object_id(object_type: str, payload: dict[str, Any]) -> str:
    clean_payload = dict(payload)
    clean_payload.pop("type", None)
    raw = object_type.encode("utf-8") + b"\0" + canonical_json(clean_payload)
    return HASH_PREFIX + hashlib.sha256(raw).hexdigest()


def is_hash(value: str) -> bool:
    if not value.startswith(HASH_PREFIX):
        return False
    digest = value[len(HASH_PREFIX) :]
    return len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)
