"""Ungit agent CLI."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Sequence

from ungit_core import DEFAULT_CORE_URL

from .runner import DEFAULT_AGENT_ROOT, AgentError, rollback, run_loop


class HelpFormatter(argparse.RawDescriptionHelpFormatter, argparse.ArgumentDefaultsHelpFormatter):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ungit-agent",
        description="Ungit deploy agent: claim jobs from core and deploy releases.",
        epilog="""examples:
  ungit-agent run --name prod-1 --core-url http://core:8765 --token <agent-token>
  UNGIT_AGENT_TOKEN=<agent-token> ungit-agent run --name prod-1
  ungit-agent rollback my-app
""",
        formatter_class=HelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser(
        "run",
        help="run agent loop",
        description="Register with core using an agent token, claim jobs, download payloads, and deploy.",
        formatter_class=HelpFormatter,
    )
    run_parser.add_argument("--name", required=True, help="agent name registered in core")
    run_parser.add_argument("--core-url", default=DEFAULT_CORE_URL, help="core service URL")
    run_parser.add_argument("--token", help="agent bearer token; overrides UNGIT_AGENT_TOKEN")
    run_parser.add_argument("--root", default=str(DEFAULT_AGENT_ROOT), help="agent runtime root")
    run_parser.add_argument("--once", action="store_true", help="claim at most one job and exit")
    run_parser.add_argument("--interval", type=float, default=2.0, help="poll interval in seconds")

    receive_parser = subparsers.add_parser(
        "receive",
        help="claim one job and exit",
        description="Compatibility alias for run --once.",
    )
    receive_parser.add_argument("--name", required=True, help="agent name registered in core")
    receive_parser.add_argument("--core-url", default=DEFAULT_CORE_URL, help="core service URL")
    receive_parser.add_argument("--token", help="agent bearer token; overrides UNGIT_AGENT_TOKEN")
    receive_parser.add_argument("--root", default=str(DEFAULT_AGENT_ROOT), help="agent runtime root")

    rollback_parser = subparsers.add_parser(
        "rollback",
        help="switch project to previous release",
        description="Rollback current symlink to previous release for one project.",
    )
    rollback_parser.add_argument("project", help="project name")
    rollback_parser.add_argument("--root", default=str(DEFAULT_AGENT_ROOT), help="agent runtime root")

    return parser


def run(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return run_loop(
                name=args.name,
                core_url=args.core_url,
                token=_agent_token(args.token),
                root=Path(args.root),
                once=args.once,
                interval=args.interval,
            )
        if args.command == "receive":
            return run_loop(
                name=args.name,
                core_url=args.core_url,
                token=_agent_token(args.token),
                root=Path(args.root),
                once=True,
            )
        if args.command == "rollback":
            return rollback(args.project, root=Path(args.root))
    except AgentError as exc:
        print(str(exc))
        return 1
    parser.error(f"unknown command: {args.command}")
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv)


def _agent_token(flag: str | None) -> str:
    token = flag or os.environ.get("UNGIT_AGENT_TOKEN")
    if not token:
        raise AgentError("missing agent token")
    return token


if __name__ == "__main__":
    raise SystemExit(main())
