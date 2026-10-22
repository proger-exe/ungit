"""Path validation shared by local and runtime storage."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from .errors import InvalidStoragePath

OBJECT_TYPES = {"blob": "blobs", "tree": "trees", "commit": "commits"}
OBJECT_DIRS = set(OBJECT_TYPES.values())


def safe_relative(value: str, *, label: str) -> Path:
    if not value:
        raise InvalidStoragePath(f"{label} is required")
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or any(part == "" for part in pure.parts):
        raise InvalidStoragePath(f"invalid {label}: {value}")
    return Path(*pure.parts)


def safe_segment(value: str, *, label: str) -> str:
    path = safe_relative(value, label=label)
    if len(path.parts) != 1:
        raise InvalidStoragePath(f"invalid {label}: {value}")
    return path.name


def object_dir(object_type: str) -> str:
    if object_type in OBJECT_TYPES:
        return OBJECT_TYPES[object_type]
    if object_type in OBJECT_DIRS:
        return object_type
    raise InvalidStoragePath(f"invalid object type: {object_type}")


def object_file_name(object_id: str) -> str:
    return f"{safe_segment(object_id, label='object id')}.json"
