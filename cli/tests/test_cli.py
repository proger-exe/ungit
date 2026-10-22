from __future__ import annotations

from io import StringIO
from pathlib import Path

from ungit_cli.main import run
from ungit_storage import LocalRepositoryStore, read_json
import ungit_cli.commands as commands
from ungit_cli.credentials import save_core_token


def invoke(tmp_path: Path, args: list[str]) -> tuple[int, str, str]:
    stdout = StringIO()
    stderr = StringIO()
    code = run(args, cwd=tmp_path, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def login_tmp(monkeypatch, tmp_path: Path, core_url: str = "http://core", token: str = "user-token") -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    save_core_token(core_url, token, "alice")


def test_init_creates_repository(tmp_path: Path) -> None:
    code, stdout, stderr = invoke(tmp_path, ["init"])

    assert code == 0
    assert stderr == ""
    assert stdout == "[init] repository ready .ungit\n"
    assert read_json(tmp_path / ".ungit" / "index.json") == {"files": []}
    assert (tmp_path / ".ungit" / "objects" / "commits").is_dir()


def test_commands_require_repository(tmp_path: Path) -> None:
    code, stdout, stderr = invoke(tmp_path, ["status"])

    assert code == 1
    assert stdout == ""
    assert stderr == "[error] not an ungit repository\n"


def test_add_indexes_files_and_ignores_internal_dirs(tmp_path: Path) -> None:
    invoke(tmp_path, ["init"])
    (tmp_path / "app.py").write_text("print(1)", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref", encoding="utf-8")

    code, stdout, stderr = invoke(tmp_path, ["add", "."])

    index = LocalRepositoryStore(tmp_path).read_index()
    assert code == 0
    assert stderr == ""
    assert stdout == "[add] added 1 files\n"
    assert [entry.path for entry in index.files] == ["app.py"]


def test_status_reports_clean_added_modified_and_deleted(tmp_path: Path) -> None:
    invoke(tmp_path, ["init"])
    (tmp_path / "app.py").write_text("v1", encoding="utf-8")
    invoke(tmp_path, ["add", "."])

    code, stdout, _ = invoke(tmp_path, ["status"])
    assert code == 0
    assert stdout == "[status] clean\n"

    (tmp_path / "app.py").write_text("v2", encoding="utf-8")
    (tmp_path / "new.py").write_text("new", encoding="utf-8")
    code, stdout, _ = invoke(tmp_path, ["status"])
    assert code == 0
    assert stdout == "~ app.py\n+ new.py\n"

    (tmp_path / "app.py").unlink()
    code, stdout, _ = invoke(tmp_path, ["status"])
    assert code == 0
    assert stdout == "- app.py\n+ new.py\n"


def test_push_creates_commit_and_updates_ref(tmp_path: Path) -> None:
    invoke(tmp_path, ["init"])
    (tmp_path / "app.py").write_text("print(1)", encoding="utf-8")
    invoke(tmp_path, ["add", "."])

    code, stdout, stderr = invoke(tmp_path, ["push", "master", "-c", "init"])

    store = LocalRepositoryStore(tmp_path)
    commit_id = store.read_ref("master")
    assert code == 0
    assert stderr == ""
    assert commit_id is not None
    assert stdout == f"[commit] created {commit_id}\n[push] local commit ready\n"
    assert store.has_object("commit", commit_id)


def test_push_requires_comment(tmp_path: Path) -> None:
    invoke(tmp_path, ["init"])

    code, stdout, stderr = invoke(tmp_path, ["push", "master"])

    assert code == 1
    assert stdout == ""
    assert stderr == "push requires -c/--comment\n"


def test_push_rejects_old_manual_code_flag(tmp_path: Path) -> None:
    invoke(tmp_path, ["init"])

    code, stdout, stderr = invoke(tmp_path, ["push", "master", "-c", "init", "--code", "test"])

    assert code == 2
    assert stderr == ""
    assert stdout == "[push] --code is not used with remote core\n"


def test_login_writes_credentials(tmp_path: Path, monkeypatch) -> None:
    invoke(tmp_path, ["init"])
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    class FakeClient:
        def __init__(self, url: str, token: str | None = None) -> None:
            assert url == "http://core"
            assert token == "user-token"

        def whoami(self) -> dict:
            return {"kind": "user", "user": {"login": "alice"}}

    monkeypatch.setattr(commands, "CoreClient", FakeClient)

    code, stdout, stderr = invoke(tmp_path, ["login", "--core-url", "http://core", "--token", "user-token"])

    assert code == 0
    assert stderr == ""
    assert stdout == "[login] alice @ http://core\n"
    assert read_json(tmp_path / "xdg" / "ungit" / "credentials.json")["cores"]["http://core"]["token"] == "user-token"


def test_agent_register_prints_agent_token(tmp_path: Path, monkeypatch) -> None:
    invoke(tmp_path, ["init"])
    login_tmp(monkeypatch, tmp_path)

    class FakeClient:
        def __init__(self, url: str, token: str | None = None) -> None:
            assert url == "http://core"
            assert token == "user-token"

        def upsert_agent(self, name: str) -> dict[str, str]:
            return {"id": "agent_1", "name": name}

        def create_agent_token(self, agent_id: str) -> dict[str, str]:
            assert agent_id == "agent_1"
            return {"token": "agent-token"}

    monkeypatch.setattr(commands, "CoreClient", FakeClient)

    code, stdout, stderr = invoke(tmp_path, ["agent", "register", "prod", "--core-url", "http://core"])

    assert code == 0
    assert stderr == ""
    assert stdout == "[agent] registered prod\n[token] agent-token\n"


def test_remote_add_writes_core_config(tmp_path: Path, monkeypatch) -> None:
    invoke(tmp_path, ["init"])
    login_tmp(monkeypatch, tmp_path)

    class FakeClient:
        def __init__(self, url: str, token: str | None = None) -> None:
            assert url == "http://core"
            assert token == "user-token"

        def upsert_repo(self, project: str) -> dict[str, str]:
            return {"id": "repo_1", "project": project}

    monkeypatch.setattr(commands, "CoreClient", FakeClient)

    code, stdout, stderr = invoke(tmp_path, ["remote", "add", "origin", "http://core/demo"])

    config = read_json(tmp_path / ".ungit" / "config.json")
    assert code == 0
    assert stderr == ""
    assert stdout == "[remote] added origin http://core/demo\n"
    assert config["remotes"]["origin"]["repo_id"] == "repo_1"


def test_pipeline_add_updates_remote_pipeline(tmp_path: Path, monkeypatch) -> None:
    invoke(tmp_path, ["init"])
    login_tmp(monkeypatch, tmp_path)
    from ungit_storage import write_json_atomic

    write_json_atomic(
        tmp_path / ".ungit" / "config.json",
        {
            "default_remote": "origin",
            "remotes": {"origin": {"core_url": "http://core", "repo_id": "repo_1", "project": "demo"}},
        },
    )

    class FakeClient:
        def __init__(self, url: str, token: str | None = None) -> None:
            assert url == "http://core"
            assert token == "user-token"

        def upsert_agent(self, name: str) -> dict[str, str]:
            return {"id": "agent_1", "name": name}

        def link_agent(self, repo_id: str, agent_id: str) -> dict:
            assert (repo_id, agent_id) == ("repo_1", "agent_1")
            return {"id": "repo_1", "project": "demo", "pipeline": ["agent_1"]}

    monkeypatch.setattr(commands, "CoreClient", FakeClient)

    code, stdout, stderr = invoke(tmp_path, ["pipeline", "add", "prod"])

    config = read_json(tmp_path / ".ungit" / "config.json")
    assert code == 0
    assert stderr == ""
    assert stdout == "[pipeline] added prod\n"
    assert config["remotes"]["origin"]["pipeline"] == ["agent_1"]


def test_linked_push_builds_payload_and_sends_generated_code(tmp_path: Path, monkeypatch) -> None:
    invoke(tmp_path, ["init"])
    login_tmp(monkeypatch, tmp_path)
    (tmp_path / "app.py").write_text("print(1)", encoding="utf-8")
    invoke(tmp_path, ["add", "."])
    from ungit_storage import write_json_atomic

    write_json_atomic(
        tmp_path / ".ungit" / "config.json",
        {
            "default_remote": "origin",
            "remotes": {
                "origin": {
                    "core_url": "http://core",
                    "repo_id": "repo_1",
                    "project": "demo",
                    "pipeline": ["agent_1"],
                }
            },
        },
    )

    class FakeClient:
        def __init__(self, url: str, token: str | None = None) -> None:
            assert url == "http://core"
            assert token == "user-token"

        def push_repo(
            self,
            repo_id: str,
            *,
            branch: str,
            commit: str,
            payload_hash: str,
            archive: Path,
        ) -> dict:
            assert repo_id == "repo_1"
            assert branch == "master"
            assert commit.startswith("sha256:")
            assert payload_hash.startswith("sha256:")
            assert Path(archive).exists()
            return {"push": {"id": "push_1"}, "jobs": [{"id": "job_1", "agent_id": "agent_1"}]}

    monkeypatch.setattr(commands, "CoreClient", FakeClient)

    code, stdout, stderr = invoke(tmp_path, ["push", "master", "-c", "init"])

    assert code == 0
    assert stderr == ""
    assert "[delivery] payload prepared\n" in stdout
    assert "[remote] pushed master -> push_1\n" in stdout
    assert "[pipeline] queued 1 jobs\n" in stdout


def test_log_empty_and_parent_chain(tmp_path: Path) -> None:
    invoke(tmp_path, ["init"])

    code, stdout, stderr = invoke(tmp_path, ["log"])
    assert code == 0
    assert stderr == ""
    assert stdout == "[log] empty\n"

    (tmp_path / "app.py").write_text("v1", encoding="utf-8")
    invoke(tmp_path, ["add", "."])
    invoke(tmp_path, ["push", "master", "-c", "first"])
    (tmp_path / "app.py").write_text("v2", encoding="utf-8")
    invoke(tmp_path, ["add", "."])
    invoke(tmp_path, ["push", "master", "-c", "second"])

    code, stdout, stderr = invoke(tmp_path, ["log"])

    lines = stdout.strip().splitlines()
    assert code == 0
    assert stderr == ""
    assert len(lines) == 2
    assert lines[0].endswith(" second")
    assert lines[1].endswith(" first")
