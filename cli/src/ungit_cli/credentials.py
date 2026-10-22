"""User credential storage for CLI auth."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ungit_storage import read_json, write_json_atomic


def credentials_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME")
    root = Path(config_home) if config_home else Path.home() / ".config"
    return root / "ungit" / "credentials.json"


def read_credentials() -> dict[str, Any]:
    path = credentials_path()
    if not path.exists():
        return {"cores": {}}
    data = read_json(path)
    if not isinstance(data, dict):
        return {"cores": {}}
    data.setdefault("cores", {})
    return data


def write_credentials(data: dict[str, Any]) -> None:
    write_json_atomic(credentials_path(), data)
    credentials_path().chmod(0o600)


def save_core_token(core_url: str, token: str, login: str) -> None:
    data = read_credentials()
    cores = data.setdefault("cores", {})
    cores[core_url.rstrip("/")] = {"token": token, "login": login}
    write_credentials(data)


def token_for_core(core_url: str) -> str | None:
    cores = read_credentials().get("cores", {})
    if not isinstance(cores, dict):
        return None
    item = cores.get(core_url.rstrip("/"))
    if not isinstance(item, dict):
        return None
    token = item.get("token")
    return str(token) if token else None
