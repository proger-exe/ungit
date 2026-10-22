"""Exercise installed entry points and a real local core HTTP process."""
import json
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import sys
import time
from urllib.request import urlopen
from urllib.error import HTTPError


def test_cli_push_deploy_failure_and_manual_rollback(tmp_path):
    bin_dir = Path(os.environ.get("UNGIT_TEST_BIN", Path(sys.executable).parent))
    env = {**os.environ, "XDG_CONFIG_HOME": str(tmp_path / "config")}
    repo = tmp_path / "project"
    repo.mkdir()
    core_root = tmp_path / "core"
    runtime = tmp_path / "runtime"

    def cli(tool, *args, expected=0):
        result = subprocess.run([str(bin_dir / tool), *args], cwd=repo, env=env,
                                capture_output=True, text=True, timeout=20)
        # Token-bearing output is intentionally never included in assertion messages.
        assert result.returncode == expected, (tool, result.returncode, result.stderr)
        return result.stdout

    def token(output):
        return re.search(r"^\[token\] (.+)$", output, re.M).group(1)

    user_token = token(cli("ungit-core", "user", "create", "test-owner", "--admin", "--root", str(core_root)))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        app_port = sock.getsockname()[1]
    app_url = f"http://127.0.0.1:{app_port}/version"
    env["UNGIT_TEST_APP_URL"] = app_url
    current = runtime / "projects/demo/current"
    health_code = (
        "import os; from pathlib import Path; from urllib.request import urlopen; "
        "actual=urlopen(os.environ['UNGIT_TEST_APP_URL'], timeout=2).read().decode(); "
        "expected=(Path(os.environ['UNGIT_RELEASE'])/'version').read_text(); "
        "assert actual == expected and actual != 'broken', (actual, expected)"
    )
    health_script = "#!/bin/sh\nexec " + shlex.quote(str(bin_dir / "python")) + " -c " + shlex.quote(health_code) + "\n"
    with (tmp_path / "core.log").open("w") as log:
        core = subprocess.Popen([str(bin_dir / "ungit-core"), "serve", "--root", str(core_root),
                                 "--port", str(port)], env=env, stdout=log, stderr=log)
        app = None
        daemon = None
        try:
            for _ in range(100):
                assert core.poll() is None, "core exited before becoming ready"
                try:
                    with urlopen(url + "/health", timeout=0.2) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(0.05)
            else:
                raise AssertionError("core startup timed out")

            app = subprocess.Popen([str(bin_dir / "python"), "-m", "http.server", str(app_port),
                                    "--bind", "127.0.0.1", "--directory", str(current)],
                                   stdout=log, stderr=log)
            for _ in range(100):
                assert app.poll() is None, "application exited before becoming ready"
                try:
                    with urlopen(app_url, timeout=0.2):
                        break
                except HTTPError as exc:
                    assert exc.code == 404  # No active release yet.
                    break
                except OSError:
                    time.sleep(0.05)
            else:
                raise AssertionError("application startup timed out")

            cli("ungit", "init")
            cli("ungit", "login", "--core-url", url, "--token", user_token)
            assert "test-owner" in cli("ungit", "whoami", "--core-url", url)
            cli("ungit", "remote", "add", "origin", url + "/demo")
            agent_token = token(cli("ungit", "agent", "register", "test-agent"))
            cli("ungit", "pipeline", "add", "test-agent")
            assert "test-agent" in cli("ungit", "pipeline", "list")
            env["UNGIT_AGENT_TOKEN"] = agent_token

            def queue(version):
                before = set((core_root / "jobs").glob("*.json"))
                (repo / "version").write_text(version)
                (repo / ".ungit/deploy/health.sh").write_text(health_script)
                cli("ungit", "add", ".")
                # A later workspace edit must not alter what was staged.
                (repo / "version").write_text("unstaged")
                cli("ungit", "push", "master", "-c", version)
                created = set((core_root / "jobs").glob("*.json")) - before
                assert len(created) == 1
                return created.pop()

            def deploy(version, *, failed=False):
                queue(version)
                cli("ungit-agent", "run", "--once", "--name", "test-agent", "--core-url", url,
                    "--root", str(runtime), expected=1 if failed else 0)

            deploy("v1")
            assert (runtime / "projects/demo/current/version").read_text() == "v1"
            with urlopen(app_url, timeout=2) as response:
                assert response.read() == b"v1"
            (repo / "obsolete").write_text("remove next time")
            deploy("v2")
            (repo / "obsolete").unlink()
            deploy("v3")
            assert current.joinpath("version").read_text() == "v3"
            with urlopen(app_url, timeout=2) as response:
                assert response.read() == b"v3"
            assert not current.joinpath("obsolete").exists()
            deploy("broken", failed=True)
            assert current.joinpath("version").read_text() == "v3"
            with urlopen(app_url, timeout=2) as response:
                assert response.read() == b"v3"
            cli("ungit-agent", "rollback", "demo", "--root", str(runtime))
            assert current.joinpath("version").read_text() == "v2"
            with urlopen(app_url, timeout=2) as response:
                assert response.read() == b"v2"
            jobs = [json.loads(p.read_text()) for p in (core_root / "jobs").glob("*.json")]
            assert sorted(j["status"] for j in jobs) == ["failed", "success", "success", "success"]
            assert len(cli("ungit", "log").splitlines()) == 4
            assert user_token not in (repo / ".ungit/config.json").read_text()
            assert agent_token not in (repo / ".ungit/config.json").read_text()

            daemon = subprocess.Popen([str(bin_dir / "ungit-agent"), "run", "--name", "test-agent",
                                       "--core-url", url, "--root", str(runtime), "--interval", "0.05"],
                                      env=env, stdout=log, stderr=log)
            for version, status in [("broken", "failed"), ("v4", "success")]:
                job_file = queue(version)
                for _ in range(100):
                    assert daemon.poll() is None, "agent stopped after a failed job"
                    if json.loads(job_file.read_text())["status"] == status:
                        break
                    time.sleep(0.05)
                else:
                    raise AssertionError(f"agent did not finish {version}")
            with urlopen(app_url, timeout=2) as response:
                assert response.read() == b"v4"
        finally:
            if daemon is not None:
                daemon.terminate()
                daemon.wait(timeout=5)
            if app is not None:
                app.terminate()
                app.wait(timeout=5)
            core.terminate()
            core.wait(timeout=5)
