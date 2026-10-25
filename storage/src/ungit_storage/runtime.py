"""Agent runtime filesystem storage."""

from __future__ import annotations

import os
import fcntl
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .errors import InvalidStoragePath, ObjectNotFound, RepositoryNotFound
from .paths import safe_segment
from .utils import read_json, write_json_atomic


def ensure_agent_project(root: str | Path, project: str) -> Path:
    project_root = _project_root(root, project)
    for directory in (
        project_root / "releases",
        project_root / "shared",
        project_root / "logs",
    ):
        _plain_path(directory).mkdir(parents=True, exist_ok=True)
    return project_root


def release_name(commit_id: str) -> str:
    # ':' (sha256:...) breaks tools that split paths on it: Docker -v, PATH, scp.
    return safe_segment(commit_id, label="commit id").replace(":", "-")


def create_release(root: str | Path, project: str, commit_id: str) -> Path:
    project_root = ensure_agent_project(root, project)
    release = project_root / "releases" / release_name(commit_id)
    release.mkdir(parents=True, exist_ok=False)
    return release


def switch_current(root: str | Path, project: str, commit_id: str) -> None:
    project_root = ensure_agent_project(root, project)
    release = _release_target(project_root, Path("releases") / release_name(commit_id))

    current = project_root / "current"
    previous = project_root / "previous"
    old_target = _read_symlink(current)
    if old_target is not None:
        _release_target(project_root, old_target)
    if old_target is not None and (project_root / old_target).resolve() == release.resolve():
        return
    state = read_state(root, project) or {"project": project}
    _replace_symlink(current, release)
    if old_target:
        _replace_symlink(previous, project_root / old_target)

    state.update(
        {
            "project": project,
            "current_commit": commit_id,
            "previous_commit": state.get("current_commit") if old_target else None,
            "current_release": str(release),
            "previous_release": str(project_root / old_target) if old_target else None,
            "last_deploy_status": "switched",
        }
    )
    write_state(root, project, state)


def rollback_current(root: str | Path, project: str, *, restore_state: dict[str, Any] | None = None) -> None:
    project_root = _existing_project_root(root, project)
    if restore_state is not None:
        state = dict(restore_state)
        targets = {}
        for name in ("current", "previous"):
            # The recorded path, not the commit: releases made before release_name() keep their ':'.
            release = state.get(f"{name}_release")
            targets[name] = _release_target(project_root, Path(release)) if release else None
        for name in ("current", "previous"):
            link = project_root / name
            if targets[name] is not None:
                _replace_symlink(link, targets[name])
            else:
                link.unlink(missing_ok=True)
                state[f"{name}_commit"] = None
                state[f"{name}_release"] = None
        state["last_deploy_status"] = "rollback"
        write_state(root, project, state)
        return
    previous = project_root / "previous"
    if not previous.is_symlink():
        raise RepositoryNotFound(f"previous release not found for project: {project}")
    target = Path(os.readlink(previous))
    release = _release_target(project_root, target)

    current = project_root / "current"
    old_target = _read_symlink(current)
    if old_target is not None:
        _release_target(project_root, old_target)
    state = read_state(root, project) or {"project": project}
    _replace_symlink(current, release)
    if old_target:
        _replace_symlink(previous, project_root / old_target)

    state.update(
        {
            "project": project,
            "current_commit": state.get("previous_commit"),
            "previous_commit": state.get("current_commit") if old_target else None,
            "current_release": str(release),
            "previous_release": str(project_root / old_target) if old_target else None,
            "last_deploy_status": "rollback",
        }
    )
    write_state(root, project, state)


def write_state(root: str | Path, project: str, state: dict[str, Any]) -> None:
    project_root = ensure_agent_project(root, project)
    write_json_atomic(_plain_path(project_root / "state.json"), state)


def read_state(root: str | Path, project: str) -> dict[str, Any] | None:
    project_root = _project_root(root, project)
    path = _plain_path(project_root / "state.json")
    if not path.exists():
        return None
    return read_json(path)


def append_log(root: str | Path, project: str, deploy_id: str, line: str) -> None:
    project_root = ensure_agent_project(root, project)
    log_name = safe_segment(deploy_id, label="deploy id")
    path = _plain_path(project_root / "logs" / f"deploy-{log_name}.log")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line.rstrip("\n") + "\n")


@contextmanager
def project_lock(root: str | Path, project: str):
    project_root = ensure_agent_project(root, project)
    with _plain_path(project_root / ".deploy.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _project_root(root: str | Path, project: str) -> Path:
    projects = _plain_path(Path(root).resolve() / "projects")
    return _plain_path(projects / safe_segment(project, label="project"))


def _plain_path(path: Path) -> Path:
    if path.is_symlink():
        raise InvalidStoragePath(f"runtime path must not be a symlink: {path}")
    return path


def _release_target(project_root: Path, target: Path) -> Path:
    releases = _plain_path(project_root / "releases")
    release = _plain_path(project_root / target).resolve()
    if release.parent != releases:
        raise InvalidStoragePath(f"release outside project: {target}")
    if not release.is_dir():
        raise ObjectNotFound(f"release missing: {target}")
    return release


def _existing_project_root(root: str | Path, project: str) -> Path:
    project_root = _project_root(root, project)
    if not project_root.exists():
        raise RepositoryNotFound(f"agent project not found: {project}")
    return project_root


def _read_symlink(path: Path) -> Path | None:
    if not path.is_symlink():
        return None
    return Path(os.readlink(path))


def _replace_symlink(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    tmp = link.with_name(f".{link.name}.tmp")
    if tmp.exists() or tmp.is_symlink():
        tmp.unlink()
    relative_target = os.path.relpath(target, link.parent)
    tmp.symlink_to(relative_target)
    os.replace(tmp, link)
