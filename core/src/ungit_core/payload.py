"""Delivery payload archive helpers."""

from __future__ import annotations

import base64
import hashlib
import shutil
import tarfile
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any

from .api import _validate_relative_path, read_commit, read_tree
from .errors import InvalidPathError
from .hashing import content_hash, object_id
from .store import RepositoryStore

PAYLOAD_NAME = "delivery.tar.gz"
DEPLOY_SCRIPTS = ("preship.sh", "ship.sh", "postship.sh", "health.sh")


class PayloadError(Exception):
    pass


def build_delivery_payload(
    store: RepositoryStore,
    repo_root: str | Path,
    *,
    project: str,
    branch: str,
    commit_id: str,
    output_dir: str | Path,
    version: str = "0.1.0",
) -> tuple[Path, str]:
    repo = Path(repo_root)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="ungit-payload-") as temp_name:
        staging = Path(temp_name) / "payload"
        files_dir = staging / "files"
        deploy_dir = staging / "deploy"
        files_dir.mkdir(parents=True)
        deploy_dir.mkdir(parents=True)

        commit = read_commit(store, commit_id)
        tree = read_tree(store, commit.tree)
        if commit.branch != branch:
            raise PayloadError("branch does not match commit")
        for entry in tree.entries:
            _validate_relative_path(entry.path)
            if not store.has_object("blob", entry.hash):
                raise PayloadError(f"snapshot missing for {entry.path}; run ungit add . again")
            data = base64.b64decode(store.read_object("blob", entry.hash)["data"], validate=True)
            if content_hash(data) != entry.hash:
                raise PayloadError(f"snapshot hash mismatch: {entry.path}")
            target = files_dir / entry.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(entry.mode)

        for name in DEPLOY_SCRIPTS:
            source = repo / ".ungit" / "deploy" / name
            target = deploy_dir / name
            if source.is_symlink() or not _inside(repo, source):
                raise PayloadError(f"deploy script must not be a symlink: {name}")
            if source.exists():
                shutil.copy2(source, target)
            else:
                target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                target.chmod(0o755)

        _write_json(staging / "commit.json", store.read_object("commit", commit_id))
        _write_json(staging / "tree.json", store.read_object("tree", commit.tree))
        payload_hash = compute_payload_hash(staging)
        manifest = {
            "project": project,
            "branch": branch,
            "commit": commit_id,
            "payload_hash": payload_hash,
            "created_at": int(time.time()),
            "ungit_version": version,
        }
        _write_json(staging / "manifest.json", manifest)

        archive = output / PAYLOAD_NAME
        with tarfile.open(archive, "w:gz") as handle:
            for path in sorted(staging.rglob("*")):
                handle.add(path, arcname=path.relative_to(staging).as_posix(), recursive=False)
        return archive, payload_hash


def extract_delivery_payload(archive: str | Path, output_dir: str | Path) -> Path:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as handle:
        names = set()
        for member in handle.getmembers():
            member_path = target / member.name
            archive_path = PurePosixPath(member.name)
            if (archive_path.is_absolute() or ".." in archive_path.parts
                    or str(archive_path) != member.name.rstrip("/")
                    or not _inside(target, member_path) or member.name in names
                    or not (member.isfile() or member.isdir())):
                raise PayloadError(f"unsafe payload path: {member.name}")
            names.add(member.name)
        handle.extractall(target, filter="data")
    return target


def read_manifest(payload_dir: str | Path) -> dict[str, Any]:
    return _read_json(Path(payload_dir) / "manifest.json")


def verify_payload(payload_dir: str | Path, expected_hash: str | None = None) -> dict[str, Any]:
    root = Path(payload_dir)
    manifest = read_manifest(root)
    actual = compute_payload_hash(root)
    manifest_hash = str(manifest.get("payload_hash") or "")
    if actual != manifest_hash:
        raise PayloadError(f"payload hash mismatch: {actual} != {manifest_hash}")
    if expected_hash is not None and actual != expected_hash:
        raise PayloadError(f"unexpected payload hash: {actual} != {expected_hash}")
    try:
        if (type(manifest.get("created_at")) is not int or manifest["created_at"] < 0
                or not isinstance(manifest.get("ungit_version"), str) or not manifest["ungit_version"].strip()):
            raise PayloadError("invalid manifest metadata")
        project = manifest["project"]
        if not isinstance(project, str) or not project or project in {".", ".."} or "/" in project:
            raise PayloadError("invalid project")
        commit = _read_json(root / "commit.json")
        tree = _read_json(root / "tree.json")
        if object_id("commit", commit) != manifest["commit"] or commit["branch"] != manifest["branch"]:
            raise PayloadError("manifest does not match commit")
        if object_id("tree", tree) != commit["tree"]:
            raise PayloadError("tree does not match commit")
        expected_files = set()
        for entry in tree["entries"]:
            path = entry["path"]
            _validate_relative_path(path)
            if path in expected_files or entry["type"] != "file":
                raise PayloadError(f"invalid tree entry: {path}")
            expected_files.add(path)
            file = root / "files" / path
            if file.is_symlink() or not file.is_file() or content_hash(file.read_bytes()) != entry["hash"]:
                raise PayloadError(f"file does not match tree: {path}")
            mode = entry.get("mode", 0o644)
            if mode not in {0o644, 0o755} or file.stat().st_mode & 0o777 != mode:
                raise PayloadError(f"mode does not match tree: {path}")
        actual_files = {p.relative_to(root / "files").as_posix() for p in (root / "files").rglob("*") if p.is_file()}
        if actual_files != expected_files:
            raise PayloadError("payload contains files outside the tree")
        for name in DEPLOY_SCRIPTS:
            if not (root / "deploy" / name).is_file():
                raise PayloadError(f"missing deploy script: {name}")
    except (KeyError, TypeError, ValueError, InvalidPathError) as exc:
        raise PayloadError(f"invalid payload: {exc}") from exc
    return manifest


def compute_payload_hash(payload_dir: str | Path) -> str:
    root = Path(payload_dir)
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative == "manifest.json":
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    import json

    path.write_text(
        json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    import json

    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise PayloadError(f"invalid json object: {path}")
    return data


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False
