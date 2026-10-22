"""Agent runtime filesystem storage."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .errors import ObjectNotFound, RepositoryNotFound
from .paths import safe_segment
from .utils import read_json, write_json_atomic


def ensure_agent_project(root: str | Path, project: str) -> Path:
    project_root = _project_root(root, project)
    for directory in (
        project_root / "releases",
        project_root / "shared",
        project_root / "logs",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return project_root


def create_release(root: str | Path, project: str, commit_id: str) -> Path:
    project_root = ensure_agent_project(root, project)
    release = project_root / "releases" / safe_segment(commit_id, label="commit id")
    release.mkdir(parents=True, exist_ok=True)
    return release


def switch_current(root: str | Path, project: str, commit_id: str) -> None:
    project_root = ensure_agent_project(root, project)
    release = project_root / "releases" / safe_segment(commit_id, label="commit id")
    if not release.exists():
        raise ObjectNotFound(f"release not found: {commit_id}")

    current = project_root / "current"
    previous = project_root / "previous"
    old_target = _read_symlink(current)
    _replace_symlink(current, release)
    if old_target:
        _replace_symlink(previous, project_root / old_target)

    state = read_state(root, project) or {"project": project}
    state.update(
        {
            "project": project,
            "current_commit": commit_id,
            "previous_commit": _commit_from_release_target(old_target),
            "current_release": str(release),
            "previous_release": str(project_root / old_target) if old_target else None,
            "last_deploy_status": "success",
        }
    )
    write_state(root, project, state)


def rollback_current(root: str | Path, project: str) -> None:
    project_root = _existing_project_root(root, project)
    previous = project_root / "previous"
    if not previous.is_symlink():
        raise RepositoryNotFound(f"previous release not found for project: {project}")
    target = Path(os.readlink(previous))
    release = target if target.is_absolute() else project_root / target
    if not release.exists():
        raise ObjectNotFound(f"previous release missing: {release}")

    current = project_root / "current"
    old_target = _read_symlink(current)
    _replace_symlink(current, release)
    if old_target:
        _replace_symlink(previous, project_root / old_target)

    state = read_state(root, project) or {"project": project}
    state.update(
        {
            "project": project,
            "current_commit": release.name,
            "previous_commit": _commit_from_release_target(old_target),
            "current_release": str(release),
            "previous_release": str(project_root / old_target) if old_target else None,
            "last_deploy_status": "rollback",
        }
    )
    write_state(root, project, state)


def write_state(root: str | Path, project: str, state: dict[str, Any]) -> None:
    project_root = ensure_agent_project(root, project)
    write_json_atomic(project_root / "state.json", state)


def read_state(root: str | Path, project: str) -> dict[str, Any] | None:
    project_root = _project_root(root, project)
    path = project_root / "state.json"
    if not path.exists():
        return None
    return read_json(path)


def append_log(root: str | Path, project: str, deploy_id: str, line: str) -> None:
    project_root = ensure_agent_project(root, project)
    log_name = safe_segment(deploy_id, label="deploy id")
    path = project_root / "logs" / f"deploy-{log_name}.log"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line.rstrip("\n") + "\n")


def _project_root(root: str | Path, project: str) -> Path:
    return Path(root) / "projects" / safe_segment(project, label="project")


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


def _commit_from_release_target(target: Path | None) -> str | None:
    if target is None:
        return None
    return target.name
