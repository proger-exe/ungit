"""Local .ungit repository storage."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ungit_core import Index

from .errors import ObjectNotFound, RepositoryNotFound
from .paths import object_dir, object_file_name, safe_relative, safe_segment
from .utils import read_json, write_json_atomic

DEPLOY_SCRIPTS = ("preship.sh", "ship.sh", "postship.sh", "health.sh")
DEFAULT_HEAD = "ref: refs/heads/master\n"
NOOP_SCRIPT = "#!/bin/sh\nexit 0\n"


class LocalRepositoryStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.ungit_dir = self.root / ".ungit"

    def ensure_repository(self) -> None:
        ensure_repository(self.root)

    def read_index(self) -> Index:
        self._require_repository()
        path = self.ungit_dir / "index.json"
        if not path.exists():
            return Index()
        return Index.from_dict(read_json(path))

    def write_index(self, index: Index) -> None:
        self._require_repository()
        write_json_atomic(self.ungit_dir / "index.json", index.to_dict())

    def clear_index(self) -> None:
        self.write_index(Index())

    def write_object(self, object_type: str, object_id: str, data: dict[str, Any]) -> None:
        self._require_repository()
        write_json_atomic(self._object_path(object_type, object_id), data)

    def read_object(self, object_type: str, object_id: str) -> dict[str, Any]:
        self._require_repository()
        path = self._object_path(object_type, object_id)
        if not path.exists():
            raise ObjectNotFound(f"object not found: {object_type} {object_id}")
        return read_json(path)

    def has_object(self, object_type: str, object_id: str) -> bool:
        self._require_repository()
        return self._object_path(object_type, object_id).exists()

    def read_ref(self, branch: str) -> str | None:
        self._require_repository()
        path = self._ref_path(branch)
        if not path.exists():
            return None
        value = path.read_text(encoding="utf-8").strip()
        return value or None

    def write_ref(self, branch: str, commit_id: str) -> None:
        self._require_repository()
        safe_segment(commit_id, label="commit id")
        path = self._ref_path(branch)
        _write_text_atomic(path, f"{commit_id}\n")

    def _require_repository(self) -> None:
        if not self.ungit_dir.exists():
            raise RepositoryNotFound(f"not an ungit repository: {self.root}")

    def _object_path(self, object_type: str, object_id: str) -> Path:
        return self.ungit_dir / "objects" / object_dir(object_type) / object_file_name(object_id)

    def _ref_path(self, branch: str) -> Path:
        return self.ungit_dir / "refs" / "heads" / safe_relative(branch, label="branch")


def ensure_repository(path: str | Path) -> LocalRepositoryStore:
    root = Path(path)
    ungit = root / ".ungit"
    for directory in (
        ungit / "objects" / "blobs",
        ungit / "objects" / "trees",
        ungit / "objects" / "commits",
        ungit / "refs" / "heads",
        ungit / "deploy",
    ):
        directory.mkdir(parents=True, exist_ok=True)

    _write_json_if_missing(ungit / "config.json", {})
    _write_json_if_missing(ungit / "index.json", {"files": []})
    _write_text_if_missing(ungit / "HEAD", DEFAULT_HEAD)
    _write_text_if_missing(ungit / "refs" / "heads" / "master", "")
    for script in DEPLOY_SCRIPTS:
        script_path = ungit / "deploy" / script
        if not script_path.exists():
            _write_text_atomic(script_path, NOOP_SCRIPT)
            script_path.chmod(script_path.stat().st_mode | 0o111)
    return LocalRepositoryStore(root)


def _write_json_if_missing(path: Path, data: Any) -> None:
    if not path.exists():
        write_json_atomic(path, data)


def _write_text_if_missing(path: Path, value: str) -> None:
    if not path.exists():
        _write_text_atomic(path, value)


def _write_text_atomic(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    with temp.open("w", encoding="utf-8") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
