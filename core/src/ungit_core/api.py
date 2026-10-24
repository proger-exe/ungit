"""Public core use cases."""

from __future__ import annotations

import base64
import time
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable

from .errors import InvalidObjectError, InvalidPathError, RepositoryError
from .hashing import content_hash, is_hash, object_id
from .models import (
    Commit,
    DeliveryManifest,
    DiffEntry,
    Index,
    IndexEntry,
    Tree,
    TreeEntry,
)
from .store import RepositoryStore

IGNORE_DIRS = {".ungit", ".git", "node_modules", ".venv", "__pycache__"}


def init_repository(store: RepositoryStore) -> None:
    store.ensure_repository()


def scan_files(root: str | Path, paths: Iterable[str | Path]) -> list[IndexEntry]:
    root_path = Path(root).resolve()
    patterns = _ignore_patterns(root_path)
    entries: list[IndexEntry] = []
    for input_path in paths:
        path = _resolve_input_path(root_path, input_path)
        if not path.exists():
            raise InvalidPathError(f"path does not exist: {input_path}")
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if _is_ignored(root_path, child, patterns):
                    continue
                if child.is_symlink():
                    raise InvalidPathError(f"symlinks are not supported: {child}")
                if child.is_file():
                    entries.append(_index_entry(root_path, child))
        elif path.is_file() and not _is_ignored(root_path, path, patterns):
            entries.append(_index_entry(root_path, path))
    return sorted(_dedupe(entries), key=lambda entry: entry.path)


def add_files(store: RepositoryStore, root: str | Path, paths: Iterable[str | Path]) -> Index:
    current = store.read_index()
    root = Path(root).resolve()
    selected = [_resolve_input_path(root, path) for path in paths]
    for path in selected:
        relative = path.relative_to(root).as_posix()
        tracked = any(entry.path == relative or entry.path.startswith(relative + "/") for entry in current.files)
        if not path.exists() and not tracked:
            raise InvalidPathError(f"path does not exist: {relative}")
    scanned = scan_files(root, [path for path in selected if path.exists()])
    by_path = {entry.path: entry for entry in current.files}
    for entry in current.files:
        file_path = root / entry.path
        if any(file_path == path or path in file_path.parents for path in selected):
            by_path.pop(entry.path)
    for entry in scanned:
        data = (root / entry.path).read_bytes()
        if content_hash(data) != entry.hash:
            raise RepositoryError(f"file changed while staging: {entry.path}; run add again")
        store.write_object("blob", entry.hash, {"data": base64.b64encode(data).decode("ascii")})
    by_path.update({entry.path: entry for entry in scanned})
    updated = Index(tuple(by_path[path] for path in sorted(by_path)))
    store.write_index(updated)
    return updated


def build_tree(index: Index) -> Tree:
    entries: list[TreeEntry] = []
    seen: set[str] = set()
    for item in sorted(index.files, key=lambda entry: entry.path):
        _validate_relative_path(item.path)
        if item.path in seen:
            raise InvalidObjectError(f"duplicate tree path: {item.path}")
        seen.add(item.path)
        entries.append(TreeEntry(path=item.path, type="file", hash=item.hash, mode=item.mode))
    return Tree(tuple(entries))


def create_commit(
    store: RepositoryStore,
    branch: str,
    message: str,
    *,
    clock: Callable[[], int] | None = None,
) -> str:
    if not branch:
        raise InvalidObjectError("branch is required")
    if not message.strip():
        raise InvalidObjectError("message is required")
    now = int(clock() if clock else time.time())
    tree = build_tree(store.read_index())
    tree_id = object_id("tree", tree.to_dict())
    store.write_object("tree", tree_id, tree.to_dict())

    parent = store.read_ref(branch)
    commit = Commit(
        tree=tree_id,
        parent=parent,
        branch=branch,
        message=message,
        created_at=now,
    )
    commit_id = object_id("commit", commit.to_dict())
    store.write_object("commit", commit_id, commit.to_dict())
    store.write_ref(branch, commit_id)
    return commit_id


def resolve_ref(store: RepositoryStore, branch: str) -> str | None:
    return store.read_ref(branch)


def read_commit(store: RepositoryStore, commit_id: str) -> Commit:
    _require_hash(commit_id, "commit")
    return Commit.from_dict(store.read_object("commit", commit_id))


def read_tree(store: RepositoryStore, tree_id: str) -> Tree:
    _require_hash(tree_id, "tree")
    return Tree.from_dict(store.read_object("tree", tree_id))


def diff_trees(old_tree: Tree, new_tree: Tree, *, include_unchanged: bool = True) -> list[DiffEntry]:
    old = {entry.path: entry for entry in old_tree.entries}
    new = {entry.path: entry for entry in new_tree.entries}
    result: list[DiffEntry] = []
    for path in sorted(set(old) | set(new)):
        old_entry = old.get(path)
        new_entry = new.get(path)
        if old_entry is None and new_entry is not None:
            result.append(DiffEntry(path=path, status="added", new_hash=new_entry.hash))
        elif old_entry is not None and new_entry is None:
            result.append(DiffEntry(path=path, status="deleted", old_hash=old_entry.hash))
        elif old_entry and new_entry and old_entry.hash != new_entry.hash:
            result.append(
                DiffEntry(
                    path=path,
                    status="modified",
                    old_hash=old_entry.hash,
                    new_hash=new_entry.hash,
                )
            )
        elif include_unchanged and old_entry and new_entry:
            result.append(
                DiffEntry(
                    path=path,
                    status="unchanged",
                    old_hash=old_entry.hash,
                    new_hash=new_entry.hash,
                )
            )
    return result


def build_delivery_manifest(
    store: RepositoryStore,
    project: str,
    branch: str,
    commit_id: str,
    payload_hash: str,
    *,
    version: str,
    clock: Callable[[], int] | None = None,
) -> DeliveryManifest:
    if not project:
        raise InvalidObjectError("project is required")
    if not branch:
        raise InvalidObjectError("branch is required")
    _require_hash(commit_id, "commit")
    _require_hash(payload_hash, "payload_hash")
    if not store.has_object("commit", commit_id):
        raise RepositoryError(f"commit not found: {commit_id}")
    return DeliveryManifest(
        project=project,
        branch=branch,
        commit=commit_id,
        payload_hash=payload_hash,
        created_at=int(clock() if clock else time.time()),
        ungit_version=version,
    )


def _resolve_input_path(root: Path, input_path: str | Path) -> Path:
    raw_path = Path(input_path)
    path = raw_path if raw_path.is_absolute() else root / raw_path
    if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root and root in p.parents):
        raise InvalidPathError(f"symlinks are not supported: {input_path}")
    resolved = path.resolve()
    if resolved != root and root not in resolved.parents:
        raise InvalidPathError(f"path outside repository root: {input_path}")
    return resolved


def _index_entry(root: Path, path: Path) -> IndexEntry:
    relative = _relative_posix(root, path)
    _validate_relative_path(relative)
    data = path.read_bytes()
    mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
    return IndexEntry(path=relative, hash=content_hash(data), size=len(data), mode=mode)


def _relative_posix(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError as exc:
        raise InvalidPathError(f"path outside repository root: {path}") from exc


def _ignore_patterns(root: Path) -> list[str]:
    # ponytail: gitignore subset (no "!" negation, no "**"); add when a project needs them
    path = root / ".ungitignore"
    if not path.is_file():
        return []
    lines = (line.strip() for line in path.read_text(encoding="utf-8").splitlines())
    return [line.rstrip("/") for line in lines if line and not line.startswith("#")]


def _is_ignored(root: Path, path: Path, patterns: Iterable[str] = ()) -> bool:
    parts = _relative_posix(root, path).split("/")
    if any(part in IGNORE_DIRS for part in parts) or path.name.endswith(".pyc"):
        return True
    prefixes = ["/" + "/".join(parts[: i + 1]) for i in range(len(parts))]
    for pattern in patterns:
        if "/" in pattern:
            anchored = "/" + pattern.lstrip("/")
            if any(PurePosixPath(prefix).match(anchored) for prefix in prefixes):
                return True
        elif any(fnmatchcase(part, pattern) for part in parts):
            return True
    return False


def _dedupe(entries: Iterable[IndexEntry]) -> list[IndexEntry]:
    by_path = {entry.path: entry for entry in entries}
    return list(by_path.values())


def _validate_relative_path(path: str) -> None:
    pure = Path(path)
    parts = pure.parts
    if pure.is_absolute() or ".." in parts or not path or path.startswith("./"):
        raise InvalidPathError(f"invalid relative path: {path}")
    if ".ungit" in parts:
        raise InvalidPathError(f".ungit path is not allowed: {path}")


def _require_hash(value: str, label: str) -> None:
    if not is_hash(value):
        raise InvalidObjectError(f"invalid {label}: {value}")
