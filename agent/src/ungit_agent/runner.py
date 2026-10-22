"""Agent deployment runner."""

from __future__ import annotations

import os
import shutil
import subprocess
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
from ungit_storage import append_log, create_release, rollback_current, switch_current

STAGES = ("preship", "ship", "postship", "health")
DEFAULT_AGENT_ROOT = Path("/opt/ungitted")


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
    out = stdout
    client = CoreClient(core_url, token=token)
    whoami = client.whoami()
    if whoami.get("kind") != "agent" or whoami["agent"].get("name") != name:
        raise AgentError("agent token does not match agent name")
    agent = whoami["agent"]
    agent_id = str(agent["id"])
    while True:
        ran = run_once(agent_id=agent_id, client=client, root=root, stdout=out)
        if once:
            return 0 if ran else 0
        time.sleep(interval)


def run_once(
    *,
    agent_id: str,
    client: CoreClient,
    root: str | Path = DEFAULT_AGENT_ROOT,
    stdout: TextIO | None = None,
) -> bool:
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
            _event(client, job_id, "verified", "[verify] ok")
            _deploy_payload(client, job_id, root, manifest, payload_dir)
    except Exception as exc:
        _event(client, job_id, "failed", f"[deploy] failed {exc}")
        raise AgentError(str(exc)) from exc
    _print(stdout, f"[deploy] success {job_id}")
    return True


def rollback(project: str, *, root: str | Path = DEFAULT_AGENT_ROOT) -> int:
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
    release = create_release(root, project, commit)
    _clear_release(release)
    _copy_payload_files(payload_dir, release)
    _event(client, deploy_id, "release_created", "[release] created")

    previous_commit = None
    state_path = Path(root) / "projects" / project / "state.json"
    if state_path.exists():
        import json

        previous_commit = json.loads(state_path.read_text(encoding="utf-8")).get("current_commit")

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
    switch_current(root, project, commit)
    _event(client, deploy_id, "switched", f"[switch] current -> releases/{commit}")
    try:
        _run_stage(client, deploy_id, root, project, release, "postship", env_base)
        _run_stage(client, deploy_id, root, project, release, "health", env_base)
    except AgentError:
        _event(client, deploy_id, "rollback", "[rollback] started")
        rollback_current(root, project)
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


def _clear_release(release: Path) -> None:
    for path in release.iterdir():
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()


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
    result = subprocess.run(
        [str(script)],
        cwd=release,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    for line in result.stdout.splitlines():
        append_log(root, project, deploy_id, line)
    if result.returncode != 0:
        line = f"[{stage}] failed exit={result.returncode}"
        _event(client, deploy_id, "failed", line)
        raise AgentError(line)
    _event(client, deploy_id, stage, f"[{stage}] ok")


def _event(client: CoreClient, deploy_id: str, status: str, line: str) -> None:
    try:
        client.add_event(deploy_id, status, line)
    except CoreClientError:
        pass


def _print(stdout: TextIO | None, line: str) -> None:
    if stdout is not None:
        print(line, file=stdout)
