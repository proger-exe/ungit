"""HTTP core service primitives."""

from __future__ import annotations

import json
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .service_store import (
    DEFAULT_CORE_ROOT,
    CoreForbidden,
    CoreNotFound,
    CoreServiceStore,
    CoreStoreError,
    CoreUnauthorized,
)


def serve_core(host: str = "127.0.0.1", port: int = 8765, root: str | Path = DEFAULT_CORE_ROOT) -> None:
    store = CoreServiceStore(root)
    store.ensure()

    class Handler(CoreRequestHandler):
        core_store = store

    server = ThreadingHTTPServer((host, port), Handler)
    server.serve_forever()


class CoreRequestHandler(BaseHTTPRequestHandler):
    core_store: CoreServiceStore

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json(200, {"ok": True})
            return
        try:
            self._route_get()
        except CoreUnauthorized as exc:
            self._json(401, {"error": str(exc)})
        except CoreForbidden as exc:
            self._json(403, {"error": str(exc)})
        except CoreNotFound as exc:
            self._json(404, {"error": str(exc)})
        except (CoreStoreError, ValueError, KeyError) as exc:
            self._json(400, {"error": str(exc)})

    def _route_get(self) -> None:
        path = urlparse(self.path).path.strip("/")
        parts = path.split("/") if path else []
        actor = self._actor()
        if parts == ["whoami"]:
            self._json(200, self.core_store.whoami(actor))
            return
        if len(parts) == 3 and parts[0] == "jobs" and parts[2] == "payload":
            payload_path = self.core_store.payload_path_for_job(parts[1], actor)
            raw = payload_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/gzip")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if len(parts) == 3 and parts[0] == "jobs" and parts[2] == "events":
            self._json(200, self.core_store.job_events(parts[1], actor))
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        try:
            self._route_post()
        except CoreUnauthorized as exc:
            self._json(401, {"error": str(exc)})
        except CoreForbidden as exc:
            self._json(403, {"error": str(exc)})
        except CoreNotFound as exc:
            self._json(404, {"error": str(exc)})
        except (CoreStoreError, ValueError, KeyError) as exc:
            self._json(400, {"error": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _route_post(self) -> None:
        path = urlparse(self.path).path.strip("/")
        parts = path.split("/") if path else []
        data = self._body()

        if parts == ["repos"]:
            self._json(200, self.core_store.upsert_repo(str(data["project"]), self._actor()))
            return
        if parts == ["agents"]:
            self._json(200, self.core_store.upsert_agent(str(data["name"]), self._actor()))
            return
        if len(parts) == 3 and parts[0] == "repos" and parts[2] == "link-agent":
            self._json(200, self.core_store.link_agent(parts[1], str(data["agent_id"]), self._actor()))
            return
        if len(parts) == 3 and parts[0] == "agents" and parts[2] == "tokens":
            self._json(200, self.core_store.create_agent_token(parts[1], self._actor()))
            return
        if len(parts) == 3 and parts[0] == "repos" and parts[2] == "pipeline":
            agent_ids = data.get("agent_ids")
            if not isinstance(agent_ids, list):
                raise ValueError("agent_ids must be a list")
            self._json(200, self.core_store.set_pipeline(parts[1], [str(item) for item in agent_ids], self._actor()))
            return
        if len(parts) == 3 and parts[0] == "repos" and parts[2] == "push":
            import tempfile

            archive_b64 = str(data["archive_b64"])
            with tempfile.NamedTemporaryFile(prefix="ungit-core-push-", suffix=".tar.gz") as temp:
                temp.write(base64.b64decode(archive_b64.encode("ascii")))
                temp.flush()
                result = self.core_store.create_push(
                    parts[1],
                    branch=str(data["branch"]),
                    commit=str(data["commit"]),
                    payload_hash=str(data["payload_hash"]),
                    payload_path=temp.name,
                    actor=self._actor(),
                )
            self._json(200, result)
            return
        if len(parts) == 4 and parts[0] == "agents" and parts[2] == "jobs" and parts[3] == "claim":
            job = self.core_store.claim_job(parts[1], self._actor())
            self._json(200, {"job": job})
            return
        if len(parts) == 3 and parts[0] == "jobs" and parts[2] == "events":
            job = self.core_store.add_event(
                parts[1],
                status=str(data["status"]),
                line=data.get("line"),
                actor=self._actor(),
            )
            self._json(200, job)
            return

        self._json(404, {"error": "not found"})

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("request body must be an object")
        return data

    def _actor(self) -> dict[str, Any]:
        value = self.headers.get("Authorization") or ""
        scheme, _, token = value.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise CoreUnauthorized("missing bearer token")
        return self.core_store.authenticate(token.strip())

    def _json(self, status_code: int, data: dict[str, Any]) -> None:
        raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
