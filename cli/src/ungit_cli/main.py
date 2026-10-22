"""Ungit CLI entrypoint."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence, TextIO
from ungit_storage import StorageError

from .commands import (
    cmd_add,
    cmd_agent_register,
    cmd_agent_link,
    cmd_init,
    cmd_login,
    cmd_log,
    cmd_pipeline_add,
    cmd_pipeline_list,
    cmd_push,
    cmd_remote_add,
    cmd_status,
    cmd_whoami,
)
from .errors import CliError


class HelpFormatter(argparse.RawDescriptionHelpFormatter, argparse.ArgumentDefaultsHelpFormatter):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ungit",
        description="Ungit: small git-like deploy CLI.",
        epilog="""common flows:
  ungit init
  ungit add .
  ungit push master -c "initial deploy"

remote deploy:
  ungit login --core-url http://core:8765 --token <user-token>
  ungit remote add origin http://core:8765/my-app
  ungit agent register prod-1
  ungit pipeline add prod-1
  ungit push master -c "deploy"

agent server:
  ungit-agent run --name prod-1 --core-url http://core:8765 --token <agent-token>
""",
        formatter_class=HelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser(
        "init",
        help="create .ungit repository metadata",
        description="Create local .ungit storage, refs, index, and deploy script templates.",
    )
    init_parser.add_argument("--cloud", help=argparse.SUPPRESS)

    add_parser = subparsers.add_parser(
        "add",
        help="stage files for next push",
        description="Add files or directories to the local Ungit index.",
        epilog='example:\n  ungit add .\n  ungit add app.py static/',
        formatter_class=HelpFormatter,
    )
    add_parser.add_argument("paths", nargs="+", help="files or directories to add")

    subparsers.add_parser(
        "status",
        help="show working tree changes",
        description="Show added, modified, and deleted files relative to the local Ungit index.",
    )

    push_parser = subparsers.add_parser(
        "push",
        help="create commit and push payload",
        description="Create a local commit. If a remote is configured, upload delivery payload to core.",
        epilog='examples:\n  ungit push master -c "initial deploy"\n  ungit push staging -c "roll frontend"',
        formatter_class=HelpFormatter,
    )
    push_parser.add_argument("branch", help="branch/ref name to update")
    push_parser.add_argument("-c", "--comment", help="commit/deploy message")
    push_parser.add_argument("--core-url", help="override remote core URL for this push")
    push_parser.add_argument("--code", help=argparse.SUPPRESS)

    log_parser = subparsers.add_parser(
        "log",
        help="show local commit log",
        description="Show local commits for a branch.",
    )
    log_parser.add_argument("branch", nargs="?", default="master", help="branch to read")

    login_parser = subparsers.add_parser(
        "login",
        help="save user token for a core",
        description="Verify a user token with core and store it in ~/.config/ungit/credentials.json.",
        epilog="example:\n  ungit login --core-url http://core:8765 --token ugt_user_...",
        formatter_class=HelpFormatter,
    )
    login_parser.add_argument("--core-url", required=True, help="core service URL")
    login_parser.add_argument("--token", required=True, help="user bearer token")

    whoami_parser = subparsers.add_parser(
        "whoami",
        help="show current core identity",
        description="Read saved credentials and print the authenticated user for a core.",
    )
    whoami_parser.add_argument("--core-url", help="core service URL; defaults to configured remote")

    remote_parser = subparsers.add_parser(
        "remote",
        help="manage remote repositories",
        description="Manage core remotes for this local project.",
    )
    remote_subparsers = remote_parser.add_subparsers(dest="remote_command", required=True)
    remote_add = remote_subparsers.add_parser(
        "add",
        help="add or create a remote repo",
        description="Add a remote. The repo is auto-created in core when authorized.",
        epilog="example:\n  ungit remote add origin http://core:8765/my-app",
        formatter_class=HelpFormatter,
    )
    remote_add.add_argument("name", help="remote name, usually origin")
    remote_add.add_argument("url", help="core URL plus repo name")

    pipeline_parser = subparsers.add_parser(
        "pipeline",
        help="manage repo agents",
        description="Configure which agents receive deploy jobs for this repo.",
    )
    pipeline_subparsers = pipeline_parser.add_subparsers(dest="pipeline_command", required=True)
    pipeline_add = pipeline_subparsers.add_parser(
        "add",
        help="add agent to pipeline",
        description="Register/link an agent name into the remote repo pipeline.",
        epilog="example:\n  ungit pipeline add prod-1",
        formatter_class=HelpFormatter,
    )
    pipeline_add.add_argument("agent_name", help="agent name, e.g. prod-1")
    pipeline_add.add_argument("--remote", default="origin", help="remote name")
    pipeline_list = pipeline_subparsers.add_parser(
        "list",
        help="list configured agents",
        description="List cached pipeline agents for a remote.",
    )
    pipeline_list.add_argument("--remote", default="origin", help="remote name")

    agent_parser = subparsers.add_parser(
        "agent",
        help="manage deploy agents",
        description="Create agent identities and one-time agent tokens.",
    )
    agent_subparsers = agent_parser.add_subparsers(dest="agent_command", required=True)
    link_parser = agent_subparsers.add_parser(
        "link",
        help="alias for pipeline add",
        description="Compatibility alias for pipeline add.",
    )
    link_parser.add_argument("agent_name", help="agent name")
    link_parser.add_argument("--core-url", help="core service URL")
    register_parser = agent_subparsers.add_parser(
        "register",
        help="create agent token",
        description="Create or reuse an agent identity and print an agent token once.",
        epilog="example:\n  ungit agent register prod-1",
        formatter_class=HelpFormatter,
    )
    register_parser.add_argument("agent_name", help="agent name")
    register_parser.add_argument("--core-url", help="core service URL; defaults to configured remote")

    return parser


def run(
    argv: Sequence[str] | None = None,
    *,
    cwd: str | Path | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    out = stdout or sys.stdout
    err = stderr or sys.stderr
    parser = build_parser()
    args = parser.parse_args(argv)
    workdir = Path(cwd) if cwd is not None else Path.cwd()

    try:
        if args.command == "init":
            return cmd_init(workdir, out)
        if args.command == "add":
            return cmd_add(workdir, args.paths, out)
        if args.command == "status":
            return cmd_status(workdir, out)
        if args.command == "push":
            return cmd_push(workdir, args.branch, args.comment, args.core_url, args.code, out)
        if args.command == "log":
            return cmd_log(workdir, args.branch, out)
        if args.command == "login":
            return cmd_login(args.core_url, args.token, out)
        if args.command == "whoami":
            return cmd_whoami(workdir, args.core_url, out)
        if args.command == "remote" and args.remote_command == "add":
            return cmd_remote_add(workdir, args.name, args.url, out)
        if args.command == "pipeline" and args.pipeline_command == "add":
            return cmd_pipeline_add(workdir, args.agent_name, args.remote, out)
        if args.command == "pipeline" and args.pipeline_command == "list":
            return cmd_pipeline_list(workdir, args.remote, out)
        if args.command == "agent" and args.agent_command == "link":
            return cmd_agent_link(workdir, args.agent_name, args.core_url, out)
        if args.command == "agent" and args.agent_command == "register":
            return cmd_agent_register(workdir, args.agent_name, args.core_url, out)
    except CliError as exc:
        print(exc.message, file=err)
        return exc.exit_code
    except (StorageError, OSError, ValueError, KeyError) as exc:
        print(f"[error] {exc}", file=err)
        return 1

    parser.error(f"unknown command: {args.command}")
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
