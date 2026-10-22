"""Working tree status helpers."""

from __future__ import annotations

from pathlib import Path

from ungit_core import Index, scan_files


def working_tree_status(root: str | Path, index: Index) -> list[tuple[str, str]]:
    root_path = Path(root)
    current = {entry.path: entry for entry in scan_files(root_path, ["."])}
    indexed = {entry.path: entry for entry in index.files}
    changes: list[tuple[str, str]] = []

    for path in sorted(set(current) | set(indexed)):
        current_entry = current.get(path)
        indexed_entry = indexed.get(path)
        if indexed_entry is None and current_entry is not None:
            changes.append(("+", path))
        elif indexed_entry is not None and current_entry is None:
            changes.append(("-", path))
        elif indexed_entry and current_entry and (indexed_entry.hash, indexed_entry.mode) != (current_entry.hash, current_entry.mode):
            changes.append(("~", path))

    return changes
