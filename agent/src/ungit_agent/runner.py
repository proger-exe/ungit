"""Agent deployment runner."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, TextIO

from ungit_core import (
    CoreClient,
    CoreClientError,
    PAYLOAD_NAME,
    extract_delivery_payload,
    verify_payload,
)
from ungit_storage import append_log, create_release, project_lock, read_state, rollback_current, switch_current, write_state

STAGES = ("preship", "ship", "postship", "health")
DEFAULT_AGENT_ROOT = Path("/opt/ungitted")
STAGE_TIMEOUT = 300


class AgentError(Exception):
    pass


def run_loop(
    *,
    name: str,
    core_url: str,
    token: str,
    root: str | Path = DEFAULT_AGENT_ROOT,
    once: bool = False,
    interval: float = 2.0,
    stdout: TextIO | None = None,
) -> int:
    out = stdout or sys.stdout
    if interval <= 0:
        raise AgentError("poll interval must be positive")
    client = CoreClient(core_url, token=token)
    whoami = client.whoami()
    if whoami.get("kind") != "agent" or whoami["agent"].get("name") != name:
        raise AgentError("agent token does not match agent name")
    agent = whoami["agent"]
    agent_id = str(agent["id"])
    while True:
        try:
            run_once(agent_id=agent_id, client=client, root=root, stdout=out)
        except (AgentError, CoreClientError) as exc:
            if once:
                raise
            _print(out, f"[agent] {exc}; waiting for next job")
        if once:
            return 0
        time.sleep(interval)


def run_once(
    *,
    agent_id: str,
    client: CoreClient,
    root: str | Path = DEFAULT_AGENT_ROOT,
    stdout: TextIO | None = None,
) -> bool:
    root = Path(root).resolve()
    job = client.claim_job(agent_id)
    if job is None:
        _print(stdout, "[deploy] idle")
        return False

    job_id = str(job["id"])
    expected_hash = str(job["payload_hash"])
    _event(client, job_id, "running", "[job] claimed")
    try:
        with tempfile.TemporaryDirectory(prefix="ungit-agent-") as temp_name:
            temp = Path(temp_name)
            archive = client.download_job_payload(job_id, temp / PAYLOAD_NAME)
            _event(client, job_id, "downloaded", "[payload] downloaded")
            payload_dir = temp / "payload"
            extract_delivery_payload(archive, payload_dir)
            manifest = verify_payload(payload_dir, expected_hash)
            for field in ("project", "branch", "commit"):
                if manifest[field] != job.get(field):
                    raise AgentError(f"payload {field} does not match job")
            if job.get("agent_id") != agent_id:
                raise AgentError("job belongs to another agent")
            _event(client, job_id, "verified", "[verify] ok")
            with project_lock(root, manifest["project"]):
                _deploy_payload(client, job_id, root, manifest, payload_dir)
    except Exception as exc:
        _event(client, job_id, "failed", f"[deploy] failed {exc}")
        raise AgentError(str(exc)) from exc
    _print(stdout, f"[deploy] success {job_id}")
    return True


def rollback(project: str, *, root: str | Path = DEFAULT_AGENT_ROOT) -> int:
    root = Path(root).resolve()
    with project_lock(root, project):
        rollback_current(root, project)
        append_log(root, project, "rollback", "[rollback] success")
    return 0


def _deploy_payload(
    client: CoreClient,
    deploy_id: str,
    root: str | Path,
    manifest: dict[str, Any],
    payload_dir: Path,
) -> None:
    project = str(manifest["project"])
    commit = str(manifest["commit"])
    branch = str(manifest["branch"])
    before = read_state(root, project) or {"project": project}
    project_root = Path(root) / "projects" / project
    current = project_root / "current"
    if (before.get("current_commit") == commit and before.get("last_deploy_status") in {"success", "rollback"}
            and current.is_symlink() and current.resolve() == project_root / "releases" / commit):
        _event(client, deploy_id, "success", "[deploy] release already current")
        return
    try:
        release = create_release(root, project, commit)
    except FileExistsError as exc:
        raise AgentError("release already exists; push a new commit or use rollback") from exc
    _copy_payload_files(payload_dir, release)
    _event(client, deploy_id, "release_created", "[release] created")

    previous_commit = before.get("current_commit")

    env_base = {
        "UNGIT_PROJECT": project,
        "UNGIT_BRANCH": branch,
        "UNGIT_COMMIT": commit,
        "UNGIT_PREVIOUS_COMMIT": previous_commit or "",
        "UNGIT_ROOT": str(Path(root) / "projects" / project),
        "UNGIT_RELEASE": str(release),
        "UNGIT_CURRENT": str(Path(root) / "projects" / project / "current"),
        "UNGIT_PREVIOUS": str(Path(root) / "projects" / project / "previous"),
        "UNGIT_SHARED": str(Path(root) / "projects" / project / "shared"),
    }

    _run_stage(client, deploy_id, root, project, release, "preship", env_base)
    _run_stage(client, deploy_id, root, project, release, "ship", env_base)
    try:
        switch_current(root, project, commit)
        _event(client, deploy_id, "switched", f"[switch] current -> releases/{commit}")
        _run_stage(client, deploy_id, root, project, release, "postship", env_base)
        _run_stage(client, deploy_id, root, project, release, "health", env_base)
        state = read_state(root, project)
        state["last_deploy_status"] = "success"
        write_state(root, project, state)
    except Exception:
        _event(client, deploy_id, "rollback", "[rollback] started")
        rollback_current(root, project, restore_state=before)
        append_log(root, project, deploy_id, "[rollback] restored previous state")
        _event(client, deploy_id, "rollback", "[rollback] success")
        raise
    _event(client, deploy_id, "success", "[deploy] success")


def _copy_payload_files(payload_dir: Path, release: Path) -> None:
    files_dir = payload_dir / "files"
    if files_dir.exists():
        for path in files_dir.rglob("*"):
            if path.is_file():
                target = release / path.relative_to(files_dir)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
    deploy_dir = release / ".ungit" / "deploy"
    deploy_dir.mkdir(parents=True, exist_ok=True)
    for source in (payload_dir / "deploy").glob("*.sh"):
        target = deploy_dir / source.name
        shutil.copy2(source, target)
        target.chmod(target.stat().st_mode | 0o111)


def _run_stage(
    client: CoreClient,
    deploy_id: str,
    root: str | Path,
    project: str,
    release: Path,
    stage: str,
    env_base: dict[str, str],
) -> None:
    script = release / ".ungit" / "deploy" / f"{stage}.sh"
    _event(client, deploy_id, stage, f"[{stage}] started")
    env = dict(os.environ)
    env.update(env_base)
    env["UNGIT_STAGE"] = stage
    append_log(root, project, deploy_id, f"[{stage}] started")
    try:
        with (Path(root) / "projects" / project / "logs" / f"deploy-{deploy_id}.log").open("a") as log:
            process = subprocess.Popen([str(script)], cwd=release, env=env,
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                returncode = process.wait(timeout=STAGE_TIMEOUT)
            except subprocess.TimeoutExpired:
                import signal

                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                append_log(root, project, deploy_id, f"[{stage}] timed out after {STAGE_TIMEOUT}s")
                raise AgentError(f"[{stage}] timed out after {STAGE_TIMEOUT}s")
    except OSError as exc:
        raise AgentError(f"[{stage}] could not start: {exc}") from exc
    if returncode != 0:
        line = f"[{stage}] failed exit={returncode}"
        append_log(root, project, deploy_id, line)
        _event(client, deploy_id, "failed", line)
        raise AgentError(line)
    _event(client, deploy_id, stage, f"[{stage}] ok")
    append_log(root, project, deploy_id, f"[{stage}] ok")


def _event(client: CoreClient, deploy_id: str, status: str, line: str) -> None:
    try:
        client.add_event(deploy_id, status, line)
    except CoreClientError:
        pass


def _print(stdout: TextIO | None, line: str) -> None:
    if stdout is not None:
        print(line, file=stdout, flush=True)
