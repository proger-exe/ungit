"""Small HTTP client for the Ungit core service."""

from __future__ import annotations

import json
import base64
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


DEFAULT_CORE_URL = "http://127.0.0.1:8765"


class CoreClientError(Exception):
    pass


class CoreClient:
    def __init__(self, base_url: str = DEFAULT_CORE_URL, token: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    def whoami(self) -> dict[str, Any]:
        return self._get_json("/whoami")

    def upsert_repo(self, project: str) -> dict[str, Any]:
        return self._post("/repos", {"project": project})

    def upsert_agent(self, name: str) -> dict[str, Any]:
        return self._post("/agents", {"name": name})

    def create_agent_token(self, agent_id: str) -> dict[str, Any]:
        return self._post(f"/agents/{agent_id}/tokens", {})

    def link_agent(self, repo_id: str, agent_id: str) -> dict[str, Any]:
        return self._post(f"/repos/{repo_id}/link-agent", {"agent_id": agent_id})

    def set_pipeline(self, repo_id: str, agent_ids: list[str]) -> dict[str, Any]:
        return self._post(f"/repos/{repo_id}/pipeline", {"agent_ids": agent_ids})

    def push_repo(
        self,
        repo_id: str,
        *,
        branch: str,
        commit: str,
        payload_hash: str,
        archive: str | Path,
    ) -> dict[str, Any]:
        return self._post(
            f"/repos/{repo_id}/push",
            {
                "branch": branch,
                "commit": commit,
                "payload_hash": payload_hash,
                "archive_b64": base64.b64encode(Path(archive).read_bytes()).decode("ascii"),
            },
        )

    def claim_job(self, agent_id: str) -> dict[str, Any] | None:
        data = self._post(f"/agents/{agent_id}/jobs/claim", {})
        job = data.get("job")
        if job is not None and not isinstance(job, dict):
            raise CoreClientError("invalid job response")
        return job

    def download_job_payload(self, job_id: str, output: str | Path) -> Path:
        request = Request(
            self.base_url + f"/jobs/{job_id}/payload",
            headers=self._headers(),
            method="GET",
        )
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read()
        except HTTPError as exc:
            payload = _read_response(exc.read())
            message = payload.get("error") or str(exc)
            raise CoreClientError(str(message)) from exc
        except OSError as exc:
            raise CoreClientError(str(exc)) from exc
        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        return target

    def job_events(self, job_id: str) -> dict[str, Any]:
        return self._get_json(f"/jobs/{job_id}/events")

    def add_event(self, job_id: str, status: str, line: str | None = None) -> dict[str, Any]:
        return self._post(f"/jobs/{job_id}/events", {"status": status, "line": line})

    def _post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=raw,
            headers=self._headers({"Content-Type": "application/json"}),
            method="POST",
        )
        return self._open_json(request)

    def _get_json(self, path: str) -> dict[str, Any]:
        request = Request(self.base_url + path, headers=self._headers(), method="GET")
        return self._open_json(request)

    def _open_json(self, request: Request) -> dict[str, Any]:
        try:
            with urlopen(request, timeout=30) as response:
                return _read_response(response.read())
        except HTTPError as exc:
            payload = _read_response(exc.read())
            message = payload.get("error") or str(exc)
            raise CoreClientError(str(message)) from exc
        except OSError as exc:
            raise CoreClientError(str(exc)) from exc

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = dict(extra or {})
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers


def _read_response(raw: bytes) -> dict[str, Any]:
    data = json.loads(raw.decode("utf-8") or "{}")
    if not isinstance(data, dict):
        raise CoreClientError("invalid core response")
    return data
