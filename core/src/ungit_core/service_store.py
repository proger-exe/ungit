"""Core service storage for users, repos, agents, pushes, and jobs."""

from __future__ import annotations

import hashlib
import secrets
import shutil
import time
import threading
from pathlib import Path
from typing import Any


DEFAULT_CORE_ROOT = Path.home() / ".local" / "share" / "ungit" / "core"


class CoreStoreError(Exception):
    pass


class CoreNotFound(CoreStoreError):
    pass


class CoreUnauthorized(CoreStoreError):
    pass


class CoreForbidden(CoreStoreError):
    pass


class CoreServiceStore:
    def __init__(self, root: str | Path = DEFAULT_CORE_ROOT) -> None:
        self.root = Path(root)
        self._claim_lock = threading.Lock()

    def ensure(self) -> None:
        for name in ("users", "tokens", "repos", "agents", "pushes", "jobs", "events", "payloads"):
            (self.root / name).mkdir(parents=True, exist_ok=True)

    def create_user(self, login: str, *, is_admin: bool = False) -> dict[str, Any]:
        self.ensure()
        if not login:
            raise CoreStoreError("login is required")
        user_id = _stable_id("user", login)
        user = self._read_optional("users", user_id) or {
            "id": user_id,
            "login": login,
            "is_admin": bool(is_admin),
            "created_at": int(time.time()),
        }
        user["login"] = login
        user["is_admin"] = bool(user.get("is_admin") or is_admin)
        self._write("users", user_id, user)
        token = self.create_user_token(user_id)
        return {"user": user, "token": token["token"]}

    def create_user_token(self, user_id: str) -> dict[str, Any]:
        self.get_user(user_id)
        raw = _raw_token("ugt_user")
        record = {
            "id": _stable_id("tok", raw),
            "kind": "user",
            "token_hash": _hash_token(raw),
            "user_id": user_id,
            "agent_id": None,
            "created_at": int(time.time()),
            "last_used_at": None,
        }
        self._write("tokens", record["id"], record)
        return {"record": record, "token": raw}

    def create_agent_token(self, agent_id: str, actor: dict[str, Any]) -> dict[str, Any]:
        agent = self.get_agent(agent_id)
        if not self._can_manage_agent(actor, agent):
            raise CoreForbidden("cannot create token for agent")
        raw = _raw_token("ugt_agent")
        record = {
            "id": _stable_id("tok", raw),
            "kind": "agent",
            "token_hash": _hash_token(raw),
            "user_id": None,
            "agent_id": agent_id,
            "created_at": int(time.time()),
            "last_used_at": None,
        }
        self._write("tokens", record["id"], record)
        return {"agent": agent, "token": raw}

    def authenticate(self, raw_token: str | None) -> dict[str, Any]:
        if not raw_token:
            raise CoreUnauthorized("missing bearer token")
        digest = _hash_token(raw_token)
        for token in self.list_tokens():
            if token.get("token_hash") != digest:
                continue
            token["last_used_at"] = int(time.time())
            self._write("tokens", str(token["id"]), token)
            if token.get("kind") == "user":
                return {"kind": "user", "token": token, "user": self.get_user(str(token["user_id"]))}
            if token.get("kind") == "agent":
                return {"kind": "agent", "token": token, "agent": self.get_agent(str(token["agent_id"]))}
        raise CoreUnauthorized("invalid bearer token")

    def whoami(self, actor: dict[str, Any]) -> dict[str, Any]:
        if actor["kind"] == "user":
            return {"kind": "user", "user": actor["user"]}
        return {"kind": "agent", "agent": actor["agent"]}

    def upsert_repo(self, project: str, actor: dict[str, Any] | None = None) -> dict[str, Any]:
        self.ensure()
        if not project:
            raise CoreStoreError("project is required")
        repo_id = _stable_id("repo", project)
        owner_user_id = actor["user"]["id"] if actor and actor["kind"] == "user" else None
        repo = self._read_optional("repos", repo_id) or {
            "id": repo_id,
            "project": project,
            "owner_user_id": owner_user_id,
            "refs": {},
            "pipeline": [],
            "created_at": int(time.time()),
        }
        if actor is not None and not self._can_manage_repo(actor, repo):
            raise CoreForbidden("cannot access repo")
        repo["project"] = project
        repo.setdefault("owner_user_id", owner_user_id)
        repo.setdefault("refs", {})
        repo.setdefault("pipeline", [])
        self._write("repos", repo_id, repo)
        return repo

    def upsert_agent(self, name: str, actor: dict[str, Any] | None = None) -> dict[str, Any]:
        self.ensure()
        if not name:
            raise CoreStoreError("agent name is required")
        agent_id = _stable_id("agent", name)
        owner_user_id = actor["user"]["id"] if actor and actor["kind"] == "user" else None
        agent = self._read_optional("agents", agent_id) or {
            "id": agent_id,
            "name": name,
            "created_by_user_id": owner_user_id,
            "created_at": int(time.time()),
        }
        if actor is not None and not self._can_manage_agent(actor, agent):
            raise CoreForbidden("cannot access agent")
        agent["name"] = name
        agent.setdefault("created_by_user_id", owner_user_id)
        self._write("agents", agent_id, agent)
        return agent

    def link_agent(
        self,
        repo_id: str,
        agent_id: str,
        actor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.add_pipeline_agent(repo_id, agent_id, actor)

    def add_pipeline_agent(
        self,
        repo_id: str,
        agent_id: str,
        actor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        repo = self.get_repo(repo_id)
        agent = self.get_agent(agent_id)
        if actor is not None and (not self._can_manage_repo(actor, repo) or not self._can_manage_agent(actor, agent)):
            raise CoreForbidden("cannot update pipeline")
        pipeline = list(repo.get("pipeline") or [])
        if agent_id not in pipeline:
            pipeline.append(agent_id)
        repo["pipeline"] = pipeline
        self._write("repos", repo_id, repo)
        return repo

    def set_pipeline(
        self,
        repo_id: str,
        agent_ids: list[str],
        actor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        repo = self.get_repo(repo_id)
        if actor is not None and not self._can_manage_repo(actor, repo):
            raise CoreForbidden("cannot update pipeline")
        for agent_id in agent_ids:
            agent = self.get_agent(agent_id)
            if actor is not None and not self._can_manage_agent(actor, agent):
                raise CoreForbidden("cannot update pipeline")
        repo["pipeline"] = list(dict.fromkeys(agent_ids))
        self._write("repos", repo_id, repo)
        return repo

    def create_push(
        self,
        repo_id: str,
        *,
        branch: str,
        commit: str,
        payload_hash: str,
        payload_path: str | Path,
        actor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        repo = self.get_repo(repo_id)
        if actor is not None and not self._can_manage_repo(actor, repo):
            raise CoreForbidden("cannot push repo")
        pipeline = list(repo.get("pipeline") or [])
        if not pipeline:
            raise CoreStoreError("repo pipeline is empty")
        push_id = _random_id("push")
        payload_target = self.root / "payloads" / f"{push_id}.tar.gz"
        payload_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(payload_path, payload_target)
        jobs = []
        for agent_id in pipeline:
            self.get_agent(agent_id)
            job_id = _random_id("job")
            job = {
                "id": job_id,
                "push_id": push_id,
                "repo_id": repo_id,
                "agent_id": agent_id,
                "project": repo["project"],
                "branch": branch,
                "commit": commit,
                "payload_hash": payload_hash,
                "status": "queued",
                "created_at": int(time.time()),
                "queued_at_ns": time.time_ns(),
                "claimed_at": None,
            }
            self._write("jobs", job_id, job)
            self._write("events", job_id, [])
            jobs.append(job)
        push = {
            "id": push_id,
            "repo_id": repo_id,
            "project": repo["project"],
            "branch": branch,
            "commit": commit,
            "payload_hash": payload_hash,
            "payload_path": str(payload_target),
            "job_ids": [job["id"] for job in jobs],
            "created_at": int(time.time()),
        }
        repo.setdefault("refs", {})[branch] = commit
        self._write("repos", repo_id, repo)
        self._write("pushes", push_id, push)
        return {"push": push, "jobs": jobs}

    def claim_job(self, agent_id: str, actor: dict[str, Any] | None = None) -> dict[str, Any] | None:
        agent = self.get_agent(agent_id)
        if actor is not None and not self._can_run_agent(actor, agent):
            raise CoreForbidden("cannot claim jobs for agent")
        with self._claim_lock:
            for job in self.list_jobs():
                if job.get("agent_id") != agent_id or job.get("status") != "queued":
                    continue
                job["status"] = "claimed"
                job["claimed_at"] = int(time.time())
                self._write("jobs", job["id"], job)
                return job
        return None

    def add_event(
        self,
        job_id: str,
        status: str,
        line: str | None = None,
        actor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        job = self.get_job(job_id)
        if actor is not None and not self._can_access_job(actor, job):
            raise CoreForbidden("cannot update job")
        event = {"status": status, "line": line, "created_at": int(time.time())}
        events = self._read_optional("events", job_id) or []
        events.append(event)
        job["status"] = status
        self._write("jobs", job_id, job)
        self._write("events", job_id, events)
        return job

    def job_events(self, job_id: str, actor: dict[str, Any] | None = None) -> dict[str, Any]:
        job = self.get_job(job_id)
        if actor is not None and not self._can_access_job(actor, job):
            raise CoreForbidden("cannot read job")
        return {"job": job, "events": self._read_optional("events", job_id) or []}

    def get_user(self, user_id: str) -> dict[str, Any]:
        return self._read_required("users", user_id)

    def get_repo(self, repo_id: str) -> dict[str, Any]:
        return self._read_required("repos", repo_id)

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        return self._read_required("agents", agent_id)

    def get_push(self, push_id: str) -> dict[str, Any]:
        return self._read_required("pushes", push_id)

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self._read_required("jobs", job_id)

    def payload_path_for_job(self, job_id: str, actor: dict[str, Any] | None = None) -> Path:
        job = self.get_job(job_id)
        if actor is not None and not self._can_access_job(actor, job):
            raise CoreForbidden("cannot access job payload")
        push = self.get_push(str(job["push_id"]))
        return Path(push["payload_path"])

    def list_jobs(self) -> list[dict[str, Any]]:
        self.ensure()
        jobs = [
            self._read_required("jobs", path.stem)
            for path in sorted((self.root / "jobs").glob("*.json"))
        ]
        return sorted(jobs, key=lambda job: (job.get("queued_at_ns", job["created_at"] * 1_000_000_000), job["id"]))

    def list_tokens(self) -> list[dict[str, Any]]:
        self.ensure()
        return [
            self._read_required("tokens", path.stem)
            for path in sorted((self.root / "tokens").glob("*.json"))
        ]

    def _read_optional(self, kind: str, item_id: str) -> Any:
        path = self._path(kind, item_id)
        if not path.exists():
            return None
        return _read_json(path)

    def _read_required(self, kind: str, item_id: str) -> dict[str, Any]:
        data = self._read_optional(kind, item_id)
        if data is None:
            raise CoreNotFound(f"{kind[:-1]} not found: {item_id}")
        return data

    def _write(self, kind: str, item_id: str, data: Any) -> None:
        _write_json(self._path(kind, item_id), data)

    def _path(self, kind: str, item_id: str) -> Path:
        if kind not in {"users", "tokens", "repos", "agents", "pushes", "jobs", "events"}:
            raise CoreStoreError(f"invalid store kind: {kind}")
        if "/" in item_id or ".." in item_id or not item_id:
            raise CoreStoreError(f"invalid id: {item_id}")
        return self.root / kind / f"{item_id}.json"

    def _can_manage_repo(self, actor: dict[str, Any], repo: dict[str, Any]) -> bool:
        return actor["kind"] == "user" and (
            bool(actor["user"].get("is_admin")) or repo.get("owner_user_id") == actor["user"]["id"]
        )

    def _can_manage_agent(self, actor: dict[str, Any], agent: dict[str, Any]) -> bool:
        return actor["kind"] == "user" and (
            bool(actor["user"].get("is_admin")) or agent.get("created_by_user_id") == actor["user"]["id"]
        )

    def _can_run_agent(self, actor: dict[str, Any], agent: dict[str, Any]) -> bool:
        return actor["kind"] == "agent" and actor["agent"]["id"] == agent["id"]

    def _can_access_job(self, actor: dict[str, Any], job: dict[str, Any]) -> bool:
        if actor["kind"] == "agent":
            return actor["agent"]["id"] == job.get("agent_id")
        if actor["kind"] == "user":
            return self._can_manage_repo(actor, self.get_repo(str(job["repo_id"])))
        return False


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def _random_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def _raw_token(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _read_json(path: Path) -> Any:
    from ungit_storage import read_json

    return read_json(path)


def _write_json(path: Path, data: Any) -> None:
    # Import lazily: storage's local repository types depend on core's models.
    from ungit_storage import write_json_atomic

    write_json_atomic(path, data)
