"""CLI command implementations."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Iterable, TextIO

from ungit_core import (
    DEFAULT_CORE_URL,
    CoreClient,
    CoreClientError,
    PayloadError,
    add_files,
    build_delivery_payload,
    create_commit,
    read_commit,
)
from ungit_core.errors import UngitCoreError
from ungit_storage import (
    LocalRepositoryStore,
    RepositoryNotFound,
    StorageError,
    ensure_repository,
    read_json,
    write_json_atomic,
)

from .errors import CliError
from .credentials import save_core_token, token_for_core
from .status import working_tree_status


def cmd_init(cwd: Path, stdout: TextIO) -> int:
    ensure_repository(cwd)
    print("[init] repository ready .ungit", file=stdout)
    return 0


def cmd_add(cwd: Path, paths: Iterable[str], stdout: TextIO) -> int:
    store = _store(cwd)
    try:
        index = add_files(store, cwd, paths)
    except (UngitCoreError, StorageError) as exc:
        raise CliError(str(exc)) from exc
    print(f"[add] added {len(index.files)} files", file=stdout)
    return 0


def cmd_status(cwd: Path, stdout: TextIO) -> int:
    store = _store(cwd)
    try:
        changes = working_tree_status(cwd, store.read_index())
    except (UngitCoreError, StorageError) as exc:
        raise CliError(str(exc)) from exc
    if not changes:
        print("[status] clean", file=stdout)
        return 0
    for marker, path in changes:
        print(f"{marker} {path}", file=stdout)
    return 0


def cmd_push(
    cwd: Path,
    branch: str,
    comment: str | None,
    core_url: str | None,
    manual_code: str | None,
    stdout: TextIO,
    *,
    wait: bool = False,
) -> int:
    if manual_code:
        print("[push] --code is not used with remote core", file=stdout)
        return 2
    if comment is None:
        raise CliError("push requires -c/--comment")

    store = _store(cwd)
    config = _read_config(cwd)
    remote = _default_remote(config)
    url = core_url or str((remote or {}).get("core_url") or DEFAULT_CORE_URL)
    token = _require_token(url) if remote else None
    try:
        commit_id = create_commit(store, branch, comment)
    except (UngitCoreError, StorageError) as exc:
        raise CliError(str(exc)) from exc

    print(f"[commit] created {commit_id}", file=stdout)
    if remote is None:
        print("[push] local commit ready", file=stdout)
        return 0

    repo_id = str(remote["repo_id"])
    project = str(remote.get("project") or cwd.name)
    try:
        with tempfile.TemporaryDirectory(prefix="ungit-delivery-") as temp_name:
            archive, payload_hash = build_delivery_payload(
                store,
                cwd,
                project=project,
                branch=branch,
                commit_id=commit_id,
                output_dir=temp_name,
            )
            print("[delivery] payload prepared", file=stdout)
            client = CoreClient(url, token=token)
            result = client.push_repo(
                repo_id,
                branch=branch,
                commit=commit_id,
                payload_hash=payload_hash,
                archive=archive,
            )
            push = result["push"]
            jobs = result["jobs"]
            print(f"[remote] pushed {branch} -> {push['id']}", file=stdout)
            print(f"[pipeline] queued {len(jobs)} jobs", file=stdout)
            if wait:
                statuses = [_follow_job(client, str(job["id"]), stdout) for job in jobs]
                return 1 if "failed" in statuses else 0
    except (CoreClientError, PayloadError, UngitCoreError, StorageError) as exc:
        raise CliError(str(exc)) from exc
    return 0


def _follow_job(client: CoreClient, job_id: str, stdout: TextIO) -> str:
    # ponytail: no timeout; a job whose agent is down stays queued until Ctrl-C.
    shown = 0
    while True:
        data = client.job_events(job_id)
        for event in data["events"][shown:]:
            if event.get("line"):
                print(event["line"], file=stdout, flush=True)
        shown = len(data["events"])
        status = str(data["job"]["status"])
        if status in ("success", "failed"):
            return status
        time.sleep(1)


def cmd_agent_link(cwd: Path, agent_name: str, core_url: str | None, stdout: TextIO) -> int:
    return cmd_pipeline_add(cwd, agent_name, "origin", stdout, core_url=core_url)


def cmd_login(core_url: str, token: str, stdout: TextIO) -> int:
    url = core_url.rstrip("/")
    try:
        whoami = CoreClient(url, token=token).whoami()
    except CoreClientError as exc:
        raise CliError(str(exc)) from exc
    if whoami.get("kind") != "user":
        raise CliError("login requires a user token")
    login = str(whoami["user"]["login"])
    save_core_token(url, token, login)
    print(f"[login] {login} @ {url}", file=stdout)
    return 0


def cmd_whoami(cwd: Path, core_url: str | None, stdout: TextIO) -> int:
    url = core_url or _default_core_url(cwd)
    token = _require_token(url)
    try:
        whoami = CoreClient(url, token=token).whoami()
    except CoreClientError as exc:
        raise CliError(str(exc)) from exc
    if whoami.get("kind") == "user":
        print(f"{whoami['user']['login']} @ {url}", file=stdout)
    else:
        print(f"{whoami['agent']['name']} @ {url}", file=stdout)
    return 0


def cmd_agent_register(cwd: Path, agent_name: str, core_url: str | None, stdout: TextIO) -> int:
    url = core_url or _default_core_url(cwd)
    token = _require_token(url)
    try:
        client = CoreClient(url, token=token)
        agent = client.upsert_agent(agent_name)
        result = client.create_agent_token(str(agent["id"]))
    except CoreClientError as exc:
        raise CliError(str(exc)) from exc
    print(f"[agent] registered {agent_name}", file=stdout)
    print(f"[token] {result['token']}", file=stdout)
    return 0


def cmd_remote_add(cwd: Path, name: str, url: str, stdout: TextIO) -> int:
    _store(cwd)
    core_url, project = _parse_remote_url(url, cwd.name)
    token = _require_token(core_url)
    try:
        client = CoreClient(core_url, token=token)
        repo = client.upsert_repo(project)
        config = _read_config(cwd)
        remotes = _remotes(config)
        remotes[name] = {"core_url": core_url, "repo_id": repo["id"], "project": repo["project"]}
        config["remotes"] = remotes
        config["default_remote"] = name
        _write_config(cwd, config)
    except (CoreClientError, StorageError) as exc:
        raise CliError(str(exc)) from exc
    print(f"[remote] added {name} {core_url}/{project}", file=stdout)
    return 0


def cmd_pipeline_add(
    cwd: Path,
    agent_name: str,
    remote_name: str,
    stdout: TextIO,
    *,
    core_url: str | None = None,
) -> int:
    _store(cwd)
    config = _read_config(cwd)
    remote = _remote(config, remote_name)
    url = core_url or str(remote.get("core_url") or DEFAULT_CORE_URL)
    token = _require_token(url)
    try:
        client = CoreClient(url, token=token)
        agent = client.upsert_agent(agent_name)
        linked = client.link_agent(str(remote["repo_id"]), str(agent["id"]))
        remote["core_url"] = url
        remote["pipeline"] = linked.get("pipeline", [])
        agents = dict(remote.get("agents") or {})
        agents[str(agent["id"])] = str(agent["name"])
        remote["agents"] = agents
        _remotes(config)[remote_name] = remote
        _write_config(cwd, config)
    except (CoreClientError, StorageError) as exc:
        raise CliError(str(exc)) from exc
    print(f"[pipeline] added {agent_name}", file=stdout)
    return 0


def cmd_pipeline_list(cwd: Path, remote_name: str, stdout: TextIO) -> int:
    _store(cwd)
    remote = _remote(_read_config(cwd), remote_name)
    pipeline = list(remote.get("pipeline") or [])
    agents = dict(remote.get("agents") or {})
    if not pipeline:
        print("[pipeline] empty", file=stdout)
        return 0
    for agent_id in pipeline:
        print(f"{agent_id} {agents.get(agent_id, '')}".rstrip(), file=stdout)
    return 0


def cmd_log(cwd: Path, branch: str, stdout: TextIO) -> int:
    store = _store(cwd)
    commit_id = store.read_ref(branch)
    if commit_id is None:
        print("[log] empty", file=stdout)
        return 0

    try:
        while commit_id:
            commit = read_commit(store, commit_id)
            print(
                f"{commit_id} {commit.branch} {commit.created_at} {commit.message}",
                file=stdout,
            )
            commit_id = commit.parent
    except (UngitCoreError, StorageError, KeyError) as exc:
        raise CliError(str(exc)) from exc
    return 0


def _store(cwd: Path) -> LocalRepositoryStore:
    store = LocalRepositoryStore(cwd)
    try:
        store.read_index()
    except RepositoryNotFound as exc:
        raise CliError("[error] not an ungit repository") from exc
    return store


def _read_config(cwd: Path) -> dict[str, object]:
    path = cwd / ".ungit" / "config.json"
    if not path.exists():
        return {}
    data = read_json(path)
    if not isinstance(data, dict):
        raise CliError("invalid .ungit/config.json")
    return data


def _write_config(cwd: Path, config: dict[str, object]) -> None:
    write_json_atomic(cwd / ".ungit" / "config.json", config)


def _parse_remote_url(value: str, default_project: str) -> tuple[str, str]:
    stripped = value.rstrip("/")
    if "/" not in stripped.removeprefix("http://").removeprefix("https://"):
        return stripped, default_project
    core_url, project = stripped.rsplit("/", 1)
    if not project:
        project = default_project
    return core_url, project


def _remotes(config: dict[str, object]) -> dict[str, dict[str, object]]:
    remotes = config.setdefault("remotes", {})
    if not isinstance(remotes, dict):
        raise CliError("invalid remotes config")
    return remotes  # type: ignore[return-value]


def _remote(config: dict[str, object], name: str) -> dict[str, object]:
    remotes = _remotes(config)
    remote = remotes.get(name)
    if not isinstance(remote, dict):
        raise CliError(f"remote not found: {name}")
    return remote


def _default_remote(config: dict[str, object]) -> dict[str, object] | None:
    remotes = config.get("remotes")
    if isinstance(remotes, dict) and remotes:
        name = str(config.get("default_remote") or "origin")
        remote = remotes.get(name)
        if isinstance(remote, dict):
            return remote
    repo_id = config.get("repo_id")
    core_url = config.get("core_url")
    if repo_id and core_url:
        return {"repo_id": repo_id, "core_url": core_url, "project": config.get("project")}
    return None


def _default_core_url(cwd: Path) -> str:
    remote = _default_remote(_read_config(cwd))
    if remote is not None:
        return str(remote.get("core_url") or DEFAULT_CORE_URL)
    return DEFAULT_CORE_URL


def _require_token(core_url: str) -> str:
    token = token_for_core(core_url)
    if not token:
        raise CliError(f"not logged in to {core_url}; run ungit login --core-url {core_url} --token <token>")
    return token
