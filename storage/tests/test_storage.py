from __future__ import annotations

import os
from pathlib import Path

import pytest

from ungit_core import Index, IndexEntry, add_files, content_hash, create_commit, read_commit
from ungit_storage import (
    InvalidStoragePath,
    LocalRepositoryStore,
    ObjectNotFound,
    RepositoryNotFound,
    append_log,
    create_release,
    ensure_agent_project,
    ensure_repository,
    read_json,
    read_state,
    rollback_current,
    switch_current,
    write_json_atomic,
    write_state,
)


def test_ensure_repository_creates_expected_structure(tmp_path: Path) -> None:
    store = ensure_repository(tmp_path)

    assert isinstance(store, LocalRepositoryStore)
    assert (tmp_path / ".ungit" / "config.json").exists()
    assert read_json(tmp_path / ".ungit" / "index.json") == {"files": []}
    assert (tmp_path / ".ungit" / "HEAD").read_text(encoding="utf-8") == "ref: refs/heads/master\n"
    assert (tmp_path / ".ungit" / "refs" / "heads" / "master").read_text(encoding="utf-8") == ""
    for object_dir in ("blobs", "trees", "commits"):
        assert (tmp_path / ".ungit" / "objects" / object_dir).is_dir()
    for script in ("preship.sh", "ship.sh", "postship.sh", "health.sh"):
        path = tmp_path / ".ungit" / "deploy" / script
        assert path.exists()
        assert os.access(path, os.X_OK)


def test_ensure_repository_is_idempotent_and_does_not_overwrite(tmp_path: Path) -> None:
    ensure_repository(tmp_path)
    config = tmp_path / ".ungit" / "config.json"
    script = tmp_path / ".ungit" / "deploy" / "ship.sh"
    config.write_text('{"project":"demo"}\n', encoding="utf-8")
    script.write_text("#!/bin/sh\necho custom\n", encoding="utf-8")

    ensure_repository(tmp_path)

    assert read_json(config) == {"project": "demo"}
    assert "custom" in script.read_text(encoding="utf-8")


def test_json_atomic_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "data.json"

    write_json_atomic(path, {"b": 2, "a": 1})

    assert path.read_text(encoding="utf-8") == '{"a":1,"b":2}\n'
    assert read_json(path) == {"a": 1, "b": 2}


def test_index_roundtrip_and_clear(tmp_path: Path) -> None:
    store = ensure_repository(tmp_path)
    index = Index((IndexEntry("app.py", "sha256:" + "a" * 64, 12),))

    store.write_index(index)
    assert store.read_index() == index

    store.clear_index()
    assert store.read_index() == Index()


def test_objects_roundtrip_and_missing(tmp_path: Path) -> None:
    store = ensure_repository(tmp_path)
    object_id = "sha256:" + "a" * 64
    data = {"type": "tree", "entries": []}

    store.write_object("tree", object_id, data)

    assert store.has_object("tree", object_id)
    assert store.read_object("tree", object_id) == data
    assert (tmp_path / ".ungit" / "objects" / "trees" / f"{object_id}.json").exists()
    with pytest.raises(ObjectNotFound):
        store.read_object("tree", "sha256:" + "b" * 64)


def test_objects_reject_invalid_type_and_traversal(tmp_path: Path) -> None:
    store = ensure_repository(tmp_path)

    with pytest.raises(InvalidStoragePath):
        store.write_object("refs", "sha256:" + "a" * 64, {})
    with pytest.raises(InvalidStoragePath):
        store.write_object("tree", "../bad", {})


def test_refs_roundtrip_missing_empty_and_nested_branch(tmp_path: Path) -> None:
    store = ensure_repository(tmp_path)
    commit_id = "sha256:" + "c" * 64

    assert store.read_ref("master") is None
    assert store.read_ref("feature/demo") is None

    store.write_ref("feature/demo", commit_id)

    assert store.read_ref("feature/demo") == commit_id
    assert (tmp_path / ".ungit" / "refs" / "heads" / "feature" / "demo").read_text(
        encoding="utf-8"
    ) == f"{commit_id}\n"
    with pytest.raises(InvalidStoragePath):
        store.write_ref("../bad", commit_id)


def test_core_integration_add_and_commit(tmp_path: Path) -> None:
    store = ensure_repository(tmp_path)
    (tmp_path / "app.py").write_text("print(1)", encoding="utf-8")

    index = add_files(store, tmp_path, ["."])
    commit_id = create_commit(store, "master", "init", clock=lambda: 10)
    commit = read_commit(store, commit_id)

    assert index.files[0].path == "app.py"
    assert index.files[0].hash == content_hash(b"print(1)")
    assert store.read_ref("master") == commit_id
    assert store.has_object("tree", commit.tree)
    assert commit.parent is None


def test_store_requires_repository(tmp_path: Path) -> None:
    store = LocalRepositoryStore(tmp_path)

    with pytest.raises(RepositoryNotFound):
        store.read_index()


def test_runtime_project_release_switch_and_rollback(tmp_path: Path) -> None:
    commit1 = "sha256:" + "1" * 64
    commit2 = "sha256:" + "2" * 64

    project_root = ensure_agent_project(tmp_path, "demo")
    release1 = create_release(tmp_path, "demo", commit1)
    release2 = create_release(tmp_path, "demo", commit2)

    assert project_root == tmp_path / "projects" / "demo"
    assert release1.exists()
    assert release2.exists()

    switch_current(tmp_path, "demo", commit1)
    assert (project_root / "current").resolve() == release1
    assert read_state(tmp_path, "demo")["current_commit"] == commit1

    switch_current(tmp_path, "demo", commit2)
    assert (project_root / "current").resolve() == release2
    assert (project_root / "previous").resolve() == release1

    rollback_current(tmp_path, "demo")
    assert (project_root / "current").resolve() == release1
    assert read_state(tmp_path, "demo")["last_deploy_status"] == "rollback"


def test_runtime_switch_requires_release(tmp_path: Path) -> None:
    ensure_agent_project(tmp_path, "demo")

    with pytest.raises(ObjectNotFound):
        switch_current(tmp_path, "demo", "sha256:" + "a" * 64)


def test_runtime_state_roundtrip(tmp_path: Path) -> None:
    state = {"project": "demo", "last_deploy_status": "success"}

    write_state(tmp_path, "demo", state)

    assert read_state(tmp_path, "demo") == state


def test_append_log_appends_lines_and_rejects_unsafe_id(tmp_path: Path) -> None:
    append_log(tmp_path, "demo", "deploy1", "[deploy] started")
    append_log(tmp_path, "demo", "deploy1", "[deploy] success\n")

    log = tmp_path / "projects" / "demo" / "logs" / "deploy-deploy1.log"
    assert log.read_text(encoding="utf-8") == "[deploy] started\n[deploy] success\n"
    with pytest.raises(InvalidStoragePath):
        append_log(tmp_path, "demo", "../bad", "x")


def test_project_lock_serializes_deploy_and_rollback(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from ungit_storage import project_lock

    started, acquired = Event(), Event()

    def other_operation():
        started.set()
        with project_lock(tmp_path, "demo"):
            acquired.set()

    with ThreadPoolExecutor(max_workers=1) as executor:
        with project_lock(tmp_path, "demo"):
            future = executor.submit(other_operation)
            assert started.wait(timeout=2)
            assert not acquired.wait(timeout=0.1)
        future.result(timeout=2)
    assert acquired.is_set()
