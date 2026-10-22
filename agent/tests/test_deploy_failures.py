import shutil

import pytest
from io import StringIO

from ungit_agent.runner import AgentError, run_once
from ungit_core import add_files, build_delivery_payload, create_commit
from ungit_storage import ensure_repository, read_state, write_state
import ungit_agent.runner as runner


class DeliveryClient:
    def __init__(self, archive, digest, commit, project="demo"):
        self.archive = archive
        self.job = {"id": "job_test", "project": project, "branch": "master",
                    "commit": commit, "payload_hash": digest, "agent_id": "agent_test"}
        self.events = []

    def claim_job(self, agent_id):
        return self.job

    def download_job_payload(self, job_id, output):
        shutil.copy2(self.archive, output)
        return output

    def add_event(self, job_id, status, line=None):
        self.events.append((status, line))


def prepare(tmp_path, version, failing_stage=None):
    repo = tmp_path / "repo"
    store = ensure_repository(repo)
    (repo / "version").write_text(version)
    for stage in ("preship", "ship", "postship", "health"):
        (repo / f".ungit/deploy/{stage}.sh").write_text(
            "#!/bin/sh\nexit " + ("1" if stage == failing_stage else "0") + "\n")
    add_files(store, repo, ["."])
    commit = create_commit(store, "master", version)
    archive, digest = build_delivery_payload(store, repo, project="demo", branch="master",
                                             commit_id=commit, output_dir=tmp_path / version)
    return DeliveryClient(archive, digest, commit)


def deploy(tmp_path, client):
    return run_once(agent_id="agent_test", client=client, root=tmp_path / "runtime")


@pytest.mark.parametrize("stage", ["preship", "ship", "postship", "health"])
def test_failed_update_preserves_working_release_and_rollback_history(tmp_path, stage):
    deploy(tmp_path, prepare(tmp_path, "v1"))
    deploy(tmp_path, prepare(tmp_path, "v2"))
    before = read_state(tmp_path / "runtime", "demo")
    with pytest.raises(AgentError):
        deploy(tmp_path, prepare(tmp_path, "v3", stage))
    project = tmp_path / "runtime/projects/demo"
    assert (project / "current/version").read_text() == "v2"
    assert (project / "previous/version").read_text() == "v1"
    after = read_state(tmp_path / "runtime", "demo")
    assert after["current_commit"] == before["current_commit"]
    assert after["previous_commit"] == before["previous_commit"]


def test_failed_first_deploy_leaves_no_current(tmp_path):
    with pytest.raises(AgentError, match="health.*exit=1"):
        deploy(tmp_path, prepare(tmp_path, "v1", "health"))
    project = tmp_path / "runtime/projects/demo"
    assert not (project / "current").is_symlink()
    assert read_state(tmp_path / "runtime", "demo")["current_commit"] is None


def test_repeated_delivery_does_not_rewrite_live_release(tmp_path):
    client = prepare(tmp_path, "v1")
    deploy(tmp_path, client)
    current = tmp_path / "runtime/projects/demo/current"
    (current / "runtime-marker").write_text("do not delete")
    deploy(tmp_path, client)
    assert (current / "runtime-marker").read_text() == "do not delete"
    assert not (current.parent / "previous").is_symlink()


def test_interrupted_release_is_not_acknowledged_as_success(tmp_path):
    client = prepare(tmp_path, "v1")
    deploy(tmp_path, client)
    state = read_state(tmp_path / "runtime", "demo")
    state["last_deploy_status"] = "switched"
    write_state(tmp_path / "runtime", "demo", state)
    client.events.clear()
    with pytest.raises(AgentError, match="release already exists"):
        deploy(tmp_path, client)
    assert not any(status == "success" for status, _ in client.events)


def test_delivery_identity_must_match_claimed_job(tmp_path):
    client = prepare(tmp_path, "v1")
    client.job["project"] = "other-project"
    with pytest.raises(AgentError, match="project"):
        deploy(tmp_path, client)
    assert not (tmp_path / "runtime/projects/demo").exists()


def test_timeout_rolls_back_and_records_failure(tmp_path, monkeypatch):
    deploy(tmp_path, prepare(tmp_path, "v1"))
    client = prepare(tmp_path, "v2")
    original = runner._copy_payload_files

    def hanging_health(payload, release):
        original(payload, release)
        (release / ".ungit/deploy/health.sh").write_text("#!/bin/sh\nsleep 30\n")

    monkeypatch.setattr(runner, "_copy_payload_files", hanging_health)
    monkeypatch.setattr(runner, "STAGE_TIMEOUT", 0.1)
    with pytest.raises(AgentError, match="timed out"):
        deploy(tmp_path, client)
    assert (tmp_path / "runtime/projects/demo/current/version").read_text() == "v1"


def test_daemon_keeps_polling_after_failed_job(monkeypatch):
    class Client:
        def whoami(self):
            return {"kind": "agent", "agent": {"name": "prod", "id": "agent_test"}}

    monkeypatch.setattr(runner, "CoreClient", lambda *a, **kw: Client())
    calls = []

    def step(**kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise AgentError("health failed")
        raise KeyboardInterrupt

    monkeypatch.setattr(runner, "run_once", step)
    monkeypatch.setattr(runner.time, "sleep", lambda _: None)
    output = StringIO()
    with pytest.raises(KeyboardInterrupt):
        runner.run_loop(name="prod", core_url="http://core", token="test", stdout=output)
    assert len(calls) == 2
    assert "waiting for next job" in output.getvalue()
