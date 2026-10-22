import json
import tarfile
import io

import pytest

from ungit_core import add_files, build_delivery_payload, create_commit, verify_payload
from ungit_core.errors import InvalidPathError
from ungit_core.payload import PayloadError, compute_payload_hash, extract_delivery_payload
from ungit_storage import ensure_repository


def delivery(tmp_path):
    repo = tmp_path / "repo"
    store = ensure_repository(repo)
    script = repo / "app.sh"
    script.write_bytes(b"#!/bin/sh\nprintf '\\377'\n")
    script.chmod(0o755)
    add_files(store, repo, ["."])
    commit = create_commit(store, "master", "snapshot")
    return repo, store, commit


def test_delivery_uses_staged_bytes_and_permissions(tmp_path):
    repo, store, commit = delivery(tmp_path)
    staged = (repo / "app.sh").read_bytes()
    (repo / "app.sh").unlink()
    archive, digest = build_delivery_payload(store, repo, project="demo", branch="master",
                                             commit_id=commit, output_dir=tmp_path / "out")
    extracted = extract_delivery_payload(archive, tmp_path / "received")
    verify_payload(extracted, digest)
    assert (extracted / "files/app.sh").read_bytes() == staged
    assert (extracted / "files/app.sh").stat().st_mode & 0o111 == 0o111
    with tarfile.open(archive) as handle:
        names = handle.getnames()
    assert len(names) == len(set(names))


@pytest.mark.parametrize("selection", [["."], ["sub"], ["sub/gone.txt"]])
def test_add_stages_deletion_only_in_selected_paths(tmp_path, selection):
    store = ensure_repository(tmp_path)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub/gone.txt").write_text("gone")
    (tmp_path / "keep.txt").write_text("keep")
    add_files(store, tmp_path, ["."])
    (tmp_path / "sub/gone.txt").unlink()
    index = add_files(store, tmp_path, selection)
    assert [entry.path for entry in index.files] == ["keep.txt"]


def test_add_rejects_symlink_to_external_file(tmp_path):
    repo, store, _ = delivery(tmp_path)
    outside = tmp_path / "secret"
    outside.write_text("private")
    (repo / "escape").symlink_to(outside)
    with pytest.raises(InvalidPathError):
        add_files(store, repo, ["."])


@pytest.mark.parametrize("tamper", ["manifest", "content", "extra", "mode"])
def test_verify_checks_identity_and_tree_even_with_recomputed_payload_hash(tmp_path, tamper):
    repo, store, commit = delivery(tmp_path)
    archive, _ = build_delivery_payload(store, repo, project="demo", branch="master",
                                        commit_id=commit, output_dir=tmp_path / "out")
    extracted = extract_delivery_payload(archive, tmp_path / "received")
    manifest_file = extracted / "manifest.json"
    manifest = json.loads(manifest_file.read_text())
    if tamper == "manifest":
        manifest["commit"] = "sha256:" + "0" * 64
    elif tamper == "content":
        (extracted / "files/app.sh").write_text("changed")
    elif tamper == "extra":
        (extracted / "files/extra").write_text("extra")
    else:
        (extracted / "files/app.sh").chmod(0o644)
    manifest["payload_hash"] = compute_payload_hash(extracted)
    manifest_file.write_text(json.dumps(manifest))
    with pytest.raises(PayloadError):
        verify_payload(extracted, manifest["payload_hash"])


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "traversal", "duplicate"])
def test_extract_rejects_unsafe_archive_members(tmp_path, kind):
    archive = tmp_path / "bad.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        member = tarfile.TarInfo("../escape" if kind == "traversal" else "files/item")
        if kind in {"symlink", "hardlink"}:
            member.type = tarfile.SYMTYPE if kind == "symlink" else tarfile.LNKTYPE
            member.linkname = "../outside"
        else:
            member.size = 1
        handle.addfile(member, io.BytesIO(b"x"))
        if kind == "duplicate":
            handle.addfile(member, io.BytesIO(b"y"))
    with pytest.raises(PayloadError):
        extract_delivery_payload(archive, tmp_path / "received")


def test_legacy_index_without_blobs_requires_restaging(tmp_path):
    repo, store, commit = delivery(tmp_path)
    for blob in (repo / ".ungit/objects/blobs").iterdir():
        blob.unlink()
    with pytest.raises(PayloadError, match="run ungit add"):
        build_delivery_payload(store, repo, project="demo", branch="master",
                               commit_id=commit, output_dir=tmp_path / "out")


@pytest.mark.parametrize("field,value", [("created_at", None), ("created_at", True),
                                         ("created_at", -1), ("ungit_version", "")])
def test_delivery_requires_manifest_metadata(tmp_path, field, value):
    repo, store, commit = delivery(tmp_path)
    archive, digest = build_delivery_payload(store, repo, project="demo", branch="master",
                                             commit_id=commit, output_dir=tmp_path / "out")
    extracted = extract_delivery_payload(archive, tmp_path / "received")
    manifest_file = extracted / "manifest.json"
    manifest = json.loads(manifest_file.read_text())
    manifest[field] = value
    manifest_file.write_text(json.dumps(manifest))
    with pytest.raises(PayloadError, match="manifest metadata"):
        verify_payload(extracted, digest)
