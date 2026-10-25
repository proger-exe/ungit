"""Filesystem storage API for Ungit."""

from .errors import InvalidStoragePath, ObjectNotFound, RepositoryNotFound, StorageError
from .local import LocalRepositoryStore, ensure_repository
from .runtime import (
    append_log,
    create_release,
    ensure_agent_project,
    project_lock,
    read_state,
    release_name,
    rollback_current,
    switch_current,
    write_state,
)
from .utils import read_json, write_json_atomic

__all__ = [
    "InvalidStoragePath",
    "LocalRepositoryStore",
    "ObjectNotFound",
    "RepositoryNotFound",
    "StorageError",
    "append_log",
    "create_release",
    "ensure_agent_project",
    "project_lock",
    "ensure_repository",
    "read_json",
    "read_state",
    "release_name",
    "rollback_current",
    "switch_current",
    "write_json_atomic",
    "write_state",
]
