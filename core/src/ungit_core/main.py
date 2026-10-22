"""Ungit core service CLI."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Sequence

from .service import serve_core
from .service_store import DEFAULT_CORE_ROOT, CoreServiceStore


class HelpFormatter(argparse.RawDescriptionHelpFormatter, argparse.ArgumentDefaultsHelpFormatter):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ungit-core",
        description="Ungit core service: remote repos, users, agents, and deploy jobs.",
        epilog="""examples:
  ungit-core serve --host 0.0.0.0 --port 8765
  ungit-core user create alice --admin
""",
        formatter_class=HelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve_parser = subparsers.add_parser(
        "serve",
        help="run HTTP core service",
        description="Run the core HTTP service.",
    )
    serve_parser.add_argument("--host", default="127.0.0.1", help="bind host")
    serve_parser.add_argument("--port", type=int, default=8765, help="bind port")
    serve_parser.add_argument("--root", help="core data root; defaults to UNGIT_CORE_ROOT or user data dir")
    user_parser = subparsers.add_parser(
        "user",
        help="manage users",
        description="Create users and bootstrap user tokens.",
    )
    user_subparsers = user_parser.add_subparsers(dest="user_command", required=True)
    create_parser = user_subparsers.add_parser(
        "create",
        help="create user and token",
        description="Create or update a user and print a bearer token once.",
    )
    create_parser.add_argument("login", help="user login")
    create_parser.add_argument("--admin", action="store_true", help="grant admin rights")
    create_parser.add_argument("--root", help="core data root")
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "serve":
        root = Path(args.root or os.environ.get("UNGIT_CORE_ROOT") or DEFAULT_CORE_ROOT)
        serve_core(args.host, args.port, root)
        return 0
    if args.command == "user" and args.user_command == "create":
        root = Path(args.root or os.environ.get("UNGIT_CORE_ROOT") or DEFAULT_CORE_ROOT)
        result = CoreServiceStore(root).create_user(args.login, is_admin=args.admin)
        print(f"[user] created {result['user']['login']}")
        print(f"[token] {result['token']}")
        return 0
    parser.error(f"unknown command: {args.command}")
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
