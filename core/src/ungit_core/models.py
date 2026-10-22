"""Core data models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


DiffStatus = Literal["added", "modified", "deleted", "unchanged"]


@dataclass(frozen=True)
class IndexEntry:
    path: str
    hash: str
    size: int
    mode: int = 0o644

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "hash": self.hash, "size": self.size, "mode": self.mode}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IndexEntry":
        return cls(path=str(data["path"]), hash=str(data["hash"]), size=int(data["size"]), mode=int(data.get("mode", 0o644)))


@dataclass(frozen=True)
class Index:
    files: tuple[IndexEntry, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"files": [entry.to_dict() for entry in self.files]}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Index":
        if not data:
            return cls()
        return cls(tuple(IndexEntry.from_dict(entry) for entry in data.get("files", [])))


@dataclass(frozen=True)
class TreeEntry:
    path: str
    type: Literal["file"]
    hash: str
    mode: int = 0o644

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "type": self.type, "hash": self.hash, "mode": self.mode}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TreeEntry":
        return cls(path=str(data["path"]), type="file", hash=str(data["hash"]), mode=int(data.get("mode", 0o644)))


@dataclass(frozen=True)
class Tree:
    entries: tuple[TreeEntry, ...]
    type: Literal["tree"] = "tree"

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "entries": [entry.to_dict() for entry in self.entries]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Tree":
        return cls(tuple(TreeEntry.from_dict(entry) for entry in data.get("entries", [])))


@dataclass(frozen=True)
class Commit:
    tree: str
    parent: str | None
    branch: str
    message: str
    created_at: int
    type: Literal["commit"] = "commit"

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "tree": self.tree,
            "parent": self.parent,
            "branch": self.branch,
            "message": self.message,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Commit":
        return cls(
            tree=str(data["tree"]),
            parent=data.get("parent"),
            branch=str(data["branch"]),
            message=str(data["message"]),
            created_at=int(data["created_at"]),
        )


@dataclass(frozen=True)
class DiffEntry:
    path: str
    status: DiffStatus
    old_hash: str | None = None
    new_hash: str | None = None


@dataclass(frozen=True)
class DeliveryManifest:
    project: str
    branch: str
    commit: str
    payload_hash: str
    created_at: int
    ungit_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "branch": self.branch,
            "commit": self.commit,
            "payload_hash": self.payload_hash,
            "created_at": self.created_at,
            "ungit_version": self.ungit_version,
        }
