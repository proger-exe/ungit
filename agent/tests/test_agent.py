from __future__ import annotations

import shutil
from pathlib import Path

from ungit_agent.runner import run_once
import ungit_agent.main as agent_main
from ungit_core import Index, IndexEntry, add_files, build_delivery_payload, create_commit


class MemoryStore:
    def __init__(self) -> None:
        self.index = Index()
        self.objects = {}
        self.refs = {}

    def ensure_repository(self) -> None:
        pass

    def read_index(self) -> Index:
        return self.index

    def write_index(self, index: Index) -> None:
        self.index = index

    def write_object(self, object_type: str, object_id: str, data: dict) -> None:
        self.objects[(object_type, object_id)] = data

    def read_object(self, object_type: str, object_id: str) -> dict:
        return self.objects[(object_type, object_id)]

    def has_object(self, object_type: str, object_id: str) -> bool:
        return (object_type, object_id) in self.objects

    def read_ref(self, branch: str) -> str | None:
        return self.refs.get(branch)

    def write_ref(self, branch: str, commit_id: str) -> None:
        self.refs[branch] = commit_id


def test_agent_run_once_receives_and_deploys(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".ungit" / "deploy").mkdir(parents=True)
    for name in ("preship.sh", "ship.sh", "postship.sh", "health.sh"):
        script = repo / ".ungit" / "deploy" / name
        script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        script.chmod(0o755)
    (repo / "app.py").write_text("print(1)", encoding="utf-8")
    store = MemoryStore()
    add_files(store, repo, ["app.py"])
    commit_id = create_commit(store, "master", "init", clock=lambda: 10)
    archive, payload_hash = build_delivery_payload(
        store,
        repo,
        project="demo",
        branch="master",
        commit_id=commit_id,
        output_dir=tmp_path / "out",
    )
    events = []

    class FakeClient:
        def __init__(self) -> None:
            self.claimed = False

        def claim_job(self, agent_id: str):
            if self.claimed:
                return None
            self.claimed = True
            return {
                "id": "job_1",
                "project": "demo",
                "branch": "master",
                "commit": commit_id,
                "agent_id": "agent_1",
                "payload_hash": payload_hash,
            }

        def download_job_payload(self, job_id: str, output: Path) -> Path:
            assert job_id == "job_1"
            shutil.copy2(archive, output)
            return output

        def add_event(self, job_id: str, status: str, line: str | None = None):
            events.append((job_id, status, line))
            return {"id": job_id, "status": status}

    ran = run_once(
        agent_id="agent_1",
        client=FakeClient(),
        root=tmp_path / "runtime",
    )

    release = tmp_path / "runtime" / "projects" / "demo" / "releases" / commit_id
    assert ran is True
    assert (release / "app.py").read_text(encoding="utf-8") == "print(1)"
    assert (tmp_path / "runtime" / "projects" / "demo" / "current").resolve() == release
    assert ("job_1", "success", "[deploy] success") in events


def test_agent_cli_token_flag_overrides_env(monkeypatch) -> None:
    seen = {}

    def fake_run_loop(**kwargs):
        seen.update(kwargs)
        return 0

    monkeypatch.setenv("UNGIT_AGENT_TOKEN", "env-token")
    monkeypatch.setattr(agent_main, "run_loop", fake_run_loop)

    code = agent_main.run(["run", "--name", "prod", "--core-url", "http://core", "--token", "flag-token"])

    assert code == 0
    assert seen["token"] == "flag-token"
