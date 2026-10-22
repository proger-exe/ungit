"""Exercise installed entry points and a real local core HTTP process."""
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from urllib.request import urlopen


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
    with (tmp_path / "core.log").open("w") as log:
        core = subprocess.Popen([str(bin_dir / "ungit-core"), "serve", "--root", str(core_root),
                                 "--port", str(port)], env=env, stdout=log, stderr=log)
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

            cli("ungit", "init")
            cli("ungit", "login", "--core-url", url, "--token", user_token)
            cli("ungit", "remote", "add", "origin", url + "/demo")
            agent_token = token(cli("ungit", "agent", "register", "test-agent"))
            cli("ungit", "pipeline", "add", "test-agent")
            env["UNGIT_AGENT_TOKEN"] = agent_token

            def deploy(version, *, failed=False):
                (repo / "version").write_text(version)
                (repo / ".ungit/deploy/health.sh").write_text("#!/bin/sh\nexit " + ("1" if failed else "0") + "\n")
                cli("ungit", "add", ".")
                # A later workspace edit must not alter what was staged.
                (repo / "version").write_text("unstaged")
                cli("ungit", "push", "master", "-c", version)
                cli("ungit-agent", "run", "--once", "--name", "test-agent", "--core-url", url,
                    "--root", str(runtime), expected=1 if failed else 0)

            deploy("v1")
            assert (runtime / "projects/demo/current/version").read_text() == "v1"
            (repo / "obsolete").write_text("remove next time")
            deploy("v2")
            (repo / "obsolete").unlink()
            deploy("v3")
            current = runtime / "projects/demo/current"
            assert current.joinpath("version").read_text() == "v3"
            assert not current.joinpath("obsolete").exists()
            deploy("broken", failed=True)
            assert current.joinpath("version").read_text() == "v3"
            cli("ungit-agent", "rollback", "demo", "--root", str(runtime))
            assert current.joinpath("version").read_text() == "v2"
            jobs = [json.loads(p.read_text()) for p in (core_root / "jobs").glob("*.json")]
            assert sorted(j["status"] for j in jobs) == ["failed", "success", "success", "success"]
            assert len(cli("ungit", "log").splitlines()) == 4
            assert user_token not in (repo / ".ungit/config.json").read_text()
            assert agent_token not in (repo / ".ungit/config.json").read_text()
        finally:
            core.terminate()
            core.wait(timeout=5)
