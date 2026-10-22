"""Delivery payload archive helpers."""

from __future__ import annotations

import hashlib
import shutil
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Any

from .api import read_commit, read_tree
from .hashing import content_hash
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
        for entry in tree.entries:
            source = repo / entry.path
            if not source.is_file():
                raise PayloadError(f"payload file missing: {entry.path}")
            target = files_dir / entry.path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

        for name in DEPLOY_SCRIPTS:
            source = repo / ".ungit" / "deploy" / name
            target = deploy_dir / name
            if source.exists():
                shutil.copy2(source, target)
            else:
                target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                target.chmod(0o755)

        _write_json(staging / "commit.json", commit.to_dict())
        _write_json(staging / "tree.json", tree.to_dict())
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
                handle.add(path, arcname=path.relative_to(staging).as_posix())
        return archive, payload_hash


def extract_delivery_payload(archive: str | Path, output_dir: str | Path) -> Path:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as handle:
        for member in handle.getmembers():
            member_path = target / member.name
            if not _inside(target, member_path):
                raise PayloadError(f"unsafe payload path: {member.name}")
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
