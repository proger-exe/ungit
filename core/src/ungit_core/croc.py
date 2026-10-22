"""croc subprocess boundary."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Sequence


Runner = Callable[..., subprocess.CompletedProcess[str]]


class CrocError(Exception):
    pass


class CrocLayer:
    def __init__(self, binary: str = "croc", runner: Runner = subprocess.run) -> None:
        self.binary = binary
        self.runner = runner

    def send(self, archive: str | Path, code: str) -> None:
        self._run([self.binary, "send", "--code", code, str(archive)])

    def receive(self, code: str, output_dir: str | Path) -> None:
        self._run([self.binary, "--out", str(output_dir), "--overwrite", code])

    def _run(self, argv: Sequence[str]) -> None:
        result = self.runner(
            list(argv),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or "croc failed"
            raise CrocError(message)
