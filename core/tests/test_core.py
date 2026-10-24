from __future__ import annotations

import hashlib
from typing import Any

import pytest

from ungit_core import (
    CoreForbidden,
    CoreServiceStore,
    CoreUnauthorized,
    Index,
    IndexEntry,
    Tree,
    TreeEntry,
    add_files,
    build_delivery_manifest,
    build_delivery_payload,
    build_tree,
    canonical_json,
    content_hash,
    create_commit,
    diff_trees,
    object_id,
    read_commit,
    read_tree,
    resolve_ref,
    scan_files,
    verify_payload,
)
from ungit_core.payload import extract_delivery_payload
from ungit_core.errors import InvalidObjectError, InvalidPathError, RepositoryError


class MemoryStore:
    def __init__(self) -> None:
        self.index = Index()
        self.objects: dict[tuple[str, str], dict[str, Any]] = {}
        self.refs: dict[str, str] = {}
        self.initialized = False

    def ensure_repository(self) -> None:
        self.initialized = True

    def read_index(self) -> Index:
        return self.index

    def write_index(self, index: Index) -> None:
        self.index = index

    def write_object(self, object_type: str, object_id: str, data: dict[str, Any]) -> None:
        self.objects[(object_type, object_id)] = data

    def read_object(self, object_type: str, object_id: str) -> dict[str, Any]:
        return self.objects[(object_type, object_id)]

    def has_object(self, object_type: str, object_id: str) -> bool:
        return (object_type, object_id) in self.objects

    def read_ref(self, branch: str) -> str | None:
        return self.refs.get(branch)

    def write_ref(self, branch: str, commit_id: str) -> None:
        self.refs[branch] = commit_id


def test_canonical_json_and_object_id_are_stable() -> None:
    left = {"b": 2, "a": 1}
    right = {"a": 1, "b": 2}

    assert canonical_json(left) == b'{"a":1,"b":2}'
    assert object_id("tree", left) == object_id("tree", right)
    assert object_id("tree", {"a": 1}) != object_id("tree", {"a": 2})


def test_content_hash_uses_raw_bytes() -> None:
    expected = "sha256:" + hashlib.sha256(b"hello").hexdigest()

    assert content_hash(b"hello") == expected


def test_scan_files_recurses_sorts_and_ignores(tmp_path) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("print(1)", encoding="utf-8")
    (tmp_path / "app" / "z.bin").write_bytes(b"\0\1")
    (tmp_path / ".ungit").mkdir()
    (tmp_path / ".ungit" / "index.json").write_text("{}", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.js").write_text("", encoding="utf-8")
    (tmp_path / "app" / "__pycache__").mkdir()
    (tmp_path / "app" / "__pycache__" / "main.pyc").write_bytes(b"x")

    entries = scan_files(tmp_path, ["."])

    assert [entry.path for entry in entries] == ["app/main.py", "app/z.bin"]
    assert entries[1].size == 2


def test_scan_files_honours_ungitignore(tmp_path) -> None:
    (tmp_path / ".ungitignore").write_text(
        "# secrets\n.env.prod\n*.log\nbuild/\n/deploy/local/*.yml\n", encoding="utf-8"
    )
    for name in (
        "app.py",
        ".env.prod",
        "deploy/.env.prod",
        "deploy/compose.yml",
        "deploy/local/dev.yml",
        "deploy/local/keep.txt",
        "nested/deploy/local/dev.yml",
        "logs/run.log",
        "web/build/index.html",
    ):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("x", encoding="utf-8")

    assert [entry.path for entry in scan_files(tmp_path, ["."])] == [
        ".ungitignore",
        "app.py",
        "deploy/compose.yml",
        "deploy/local/keep.txt",
        "nested/deploy/local/dev.yml",
    ]
    assert scan_files(tmp_path, ["deploy/.env.prod"]) == []


def test_scan_files_ignores_symlinks_inside_ignored_dirs(tmp_path) -> None:
    external = tmp_path.parent / "python3.12"
    external.write_text("python", encoding="utf-8")
    (tmp_path / "app.py").write_text("print(1)", encoding="utf-8")
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python").symlink_to(external)

    entries = scan_files(tmp_path, ["."])

    assert [entry.path for entry in entries] == ["app.py"]


def test_scan_files_rejects_outside_root(tmp_path) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("x", encoding="utf-8")

    with pytest.raises(InvalidPathError):
        scan_files(tmp_path, [outside])


def test_add_files_updates_existing_paths_and_preserves_others(tmp_path) -> None:
    store = MemoryStore()
    store.index = Index((IndexEntry("old.txt", "sha256:" + "1" * 64, 3),))
    (tmp_path / "app.py").write_text("v1", encoding="utf-8")
    add_files(store, tmp_path, ["app.py"])
    (tmp_path / "app.py").write_text("v2", encoding="utf-8")

    updated = add_files(store, tmp_path, ["app.py"])

    assert [entry.path for entry in updated.files] == ["app.py", "old.txt"]
    assert updated.files[0].hash == content_hash(b"v2")
    assert updated.files[1].path == "old.txt"


def test_build_tree_sorts_and_rejects_invalid_paths() -> None:
    index = Index(
        (
            IndexEntry("b.txt", "sha256:" + "b" * 64, 1),
            IndexEntry("a.txt", "sha256:" + "a" * 64, 1),
        )
    )

    tree = build_tree(index)

    assert [entry.path for entry in tree.entries] == ["a.txt", "b.txt"]

    with pytest.raises(InvalidPathError):
        build_tree(Index((IndexEntry(".ungit/config.json", "sha256:" + "1" * 64, 1),)))


def test_build_tree_rejects_duplicate_paths() -> None:
    index = Index(
        (
            IndexEntry("a.txt", "sha256:" + "a" * 64, 1),
            IndexEntry("a.txt", "sha256:" + "b" * 64, 1),
        )
    )

    with pytest.raises(InvalidObjectError):
        build_tree(index)


def test_create_commit_writes_tree_commit_and_ref() -> None:
    store = MemoryStore()
    store.index = Index((IndexEntry("a.txt", "sha256:" + "a" * 64, 1),))

    first = create_commit(store, "master", "init", clock=lambda: 10)
    second = create_commit(store, "master", "next", clock=lambda: 20)

    first_commit = read_commit(store, first)
    second_commit = read_commit(store, second)
    tree = read_tree(store, second_commit.tree)

    assert first_commit.parent is None
    assert second_commit.parent == first
    assert resolve_ref(store, "master") == second
    assert tree.entries[0].path == "a.txt"


def test_create_commit_requires_message() -> None:
    store = MemoryStore()

    with pytest.raises(InvalidObjectError):
        create_commit(store, "master", " ")


def test_diff_trees_reports_all_statuses_sorted() -> None:
    old = Tree(
        (
            TreeEntry("deleted.txt", "file", "sha256:" + "d" * 64),
            TreeEntry("modified.txt", "file", "sha256:" + "1" * 64),
            TreeEntry("same.txt", "file", "sha256:" + "s" * 64),
        )
    )
    new = Tree(
        (
            TreeEntry("added.txt", "file", "sha256:" + "a" * 64),
            TreeEntry("modified.txt", "file", "sha256:" + "2" * 64),
            TreeEntry("same.txt", "file", "sha256:" + "s" * 64),
        )
    )

    diff = diff_trees(old, new)

    assert [(entry.path, entry.status) for entry in diff] == [
        ("added.txt", "added"),
        ("deleted.txt", "deleted"),
        ("modified.txt", "modified"),
        ("same.txt", "unchanged"),
    ]


def test_diff_trees_can_hide_unchanged() -> None:
    tree = Tree((TreeEntry("same.txt", "file", "sha256:" + "s" * 64),))

    assert diff_trees(tree, tree, include_unchanged=False) == []


def test_build_delivery_manifest_validates_commit_and_hash() -> None:
    store = MemoryStore()
    store.index = Index((IndexEntry("a.txt", "sha256:" + "a" * 64, 1),))
    commit_id = create_commit(store, "master", "init", clock=lambda: 10)
    payload_hash = "sha256:" + "f" * 64

    manifest = build_delivery_manifest(
        store,
        "test-app",
        "master",
        commit_id,
        payload_hash,
        version="0.1.0",
        clock=lambda: 20,
    )

    assert manifest.to_dict() == {
        "project": "test-app",
        "branch": "master",
        "commit": commit_id,
        "payload_hash": payload_hash,
        "created_at": 20,
        "ungit_version": "0.1.0",
    }

    with pytest.raises(RepositoryError):
        build_delivery_manifest(
            store,
            "test-app",
            "master",
            "sha256:" + "0" * 64,
            payload_hash,
            version="0.1.0",
        )


def test_core_service_store_pipeline_push_and_claim_job(tmp_path) -> None:
    store = CoreServiceStore(tmp_path)
    payload = tmp_path / "delivery.tar.gz"
    payload.write_bytes(b"payload")

    repo = store.upsert_repo("demo")
    agent = store.upsert_agent("prod")
    store.link_agent(repo["id"], agent["id"])
    result = store.create_push(
        repo["id"],
        branch="master",
        commit="sha256:" + "a" * 64,
        payload_hash="sha256:" + "b" * 64,
        payload_path=payload,
    )

    claimed = store.claim_job(agent["id"])

    assert len(result["jobs"]) == 1
    assert claimed is not None
    assert claimed["id"] == result["jobs"][0]["id"]
    assert store.payload_path_for_job(claimed["id"]).read_bytes() == b"payload"
    assert store.claim_job(agent["id"]) is None


def test_core_service_store_auth_user_and_agent_permissions(tmp_path) -> None:
    store = CoreServiceStore(tmp_path)
    payload = tmp_path / "delivery.tar.gz"
    payload.write_bytes(b"payload")
    alice_token = store.create_user("alice", is_admin=True)["token"]
    bob_token = store.create_user("bob")["token"]
    alice = store.authenticate(alice_token)
    bob = store.authenticate(bob_token)

    repo = store.upsert_repo("demo", alice)
    agent = store.upsert_agent("prod", alice)
    agent_token = store.create_agent_token(agent["id"], alice)["token"]
    store.link_agent(repo["id"], agent["id"], alice)
    result = store.create_push(
        repo["id"],
        branch="master",
        commit="sha256:" + "a" * 64,
        payload_hash="sha256:" + "b" * 64,
        payload_path=payload,
        actor=alice,
    )
    agent_actor = store.authenticate(agent_token)

    with pytest.raises(CoreUnauthorized):
        store.authenticate("bad-token")
    with pytest.raises(CoreForbidden):
        store.create_push(
            repo["id"],
            branch="master",
            commit="sha256:" + "a" * 64,
            payload_hash="sha256:" + "b" * 64,
            payload_path=payload,
            actor=bob,
        )

    claimed = store.claim_job(agent["id"], agent_actor)

    assert claimed is not None
    assert claimed["id"] == result["jobs"][0]["id"]
    assert store.payload_path_for_job(claimed["id"], agent_actor).read_bytes() == b"payload"


def test_delivery_payload_roundtrip_and_verify(tmp_path) -> None:
    store = MemoryStore()
    (tmp_path / ".ungit" / "deploy").mkdir(parents=True)
    for name in ("preship.sh", "ship.sh", "postship.sh", "health.sh"):
        script = tmp_path / ".ungit" / "deploy" / name
        script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        script.chmod(0o755)
    (tmp_path / "app.py").write_text("print(1)", encoding="utf-8")
    add_files(store, tmp_path, ["app.py"])
    commit_id = create_commit(store, "master", "init", clock=lambda: 10)

    archive, payload_hash = build_delivery_payload(
        store,
        tmp_path,
        project="demo",
        branch="master",
        commit_id=commit_id,
        output_dir=tmp_path / "out",
    )
    payload_dir = extract_delivery_payload(archive, tmp_path / "received")
    manifest = verify_payload(payload_dir, payload_hash)

    assert manifest["project"] == "demo"
    assert (payload_dir / "files" / "app.py").read_text(encoding="utf-8") == "print(1)"
