from pathlib import Path

import pytest

from ungit_storage import (
    InvalidStoragePath, append_log, create_release, ensure_agent_project,
    project_lock, read_state, rollback_current, switch_current,
)


@pytest.mark.parametrize("component", ["projects", "project", "releases", "logs", "shared"])
def test_runtime_directories_cannot_redirect_writes(tmp_path, component):
    root = tmp_path / "runtime"
    outside = tmp_path / "outside"
    outside.mkdir()
    if component == "projects":
        root.mkdir()
        (root / "projects").symlink_to(outside, target_is_directory=True)
    elif component == "project":
        (root / "projects").mkdir(parents=True)
        (root / "projects/demo").symlink_to(outside, target_is_directory=True)
    else:
        project = ensure_agent_project(root, "demo")
        (project / component).rmdir()
        (project / component).symlink_to(outside, target_is_directory=True)
    with pytest.raises(InvalidStoragePath):
        create_release(root, "demo", "release1")
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("name", ["logs/deploy-job1.log", ".deploy.lock", "state.json"])
def test_runtime_files_cannot_redirect_io(tmp_path, name):
    root = tmp_path / "runtime"
    project = ensure_agent_project(root, "demo")
    outside = tmp_path / "outside"
    outside.write_text('{"secret":"untouched"}')
    (project / name).symlink_to(outside)
    with pytest.raises(InvalidStoragePath):
        if name.startswith("logs"):
            append_log(root, "demo", "job1", "must not append")
        elif name == "state.json":
            read_state(root, "demo")
        else:
            with project_lock(root, "demo"):
                pass
    assert outside.read_text() == '{"secret":"untouched"}'


@pytest.mark.parametrize("link", ["previous", "current", "releases/fake"])
def test_switch_and_rollback_reject_external_targets(tmp_path, link):
    root = tmp_path / "runtime"
    release = create_release(root, "demo", "good")
    project = release.parent.parent
    outside = tmp_path / "outside"
    outside.mkdir()
    (project / link).symlink_to(outside)
    with pytest.raises(InvalidStoragePath):
        if link == "previous":
            rollback_current(root, "demo")
        elif link == "current":
            switch_current(root, "demo", "good")
        else:
            switch_current(root, "demo", "fake")
    assert list(outside.iterdir()) == []
