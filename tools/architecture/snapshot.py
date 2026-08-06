#    QPane + CuteCanvas + Ferrastra - Native graphics architecture tooling
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""Expose a read-only repository snapshot from the Git index."""

from __future__ import annotations

import subprocess
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory


class SnapshotError(RuntimeError):
    """Report inability to inspect the exact staged repository state."""


@contextmanager
def repository_snapshot(root: Path, *, staged: bool) -> Generator[Path]:
    """Yield the worktree or a temporary export of the current Git index."""
    if not staged:
        yield root
        return
    with TemporaryDirectory(prefix="ferrastra-architecture-") as directory:
        snapshot = Path(directory)
        prefix = f"{snapshot.as_posix().rstrip('/')}/"
        result = subprocess.run(
            ("git", "checkout-index", "--all", "--force", f"--prefix={prefix}"),
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise SnapshotError(
                result.stderr.strip() or "Git could not export the staged tree"
            )
        yield snapshot
