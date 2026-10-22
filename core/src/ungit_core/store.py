"""Storage protocol consumed by core."""

from __future__ import annotations

from typing import Any, Protocol

from .models import Index


class RepositoryStore(Protocol):
    def ensure_repository(self) -> None:
        ...

    def read_index(self) -> Index:
        ...

    def write_index(self, index: Index) -> None:
        ...

    def write_object(self, object_type: str, object_id: str, data: dict[str, Any]) -> None:
        ...

    def read_object(self, object_type: str, object_id: str) -> dict[str, Any]:
        ...

    def has_object(self, object_type: str, object_id: str) -> bool:
        ...

    def read_ref(self, branch: str) -> str | None:
        ...

    def write_ref(self, branch: str, commit_id: str) -> None:
        ...
