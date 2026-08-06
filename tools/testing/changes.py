#    QPane + CuteCanvas - High-performance PySide6 rendering and editing
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

"""Read changed repository paths from Git without mutating the worktree."""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitChangeError(RuntimeError):
    """Report failure to inspect repository change state."""


def worktree_paths(root: Path) -> tuple[str, ...]:
    """Return staged, unstaged, and untracked paths from porcelain status."""
    output = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    return parse_porcelain_z(output)


def parse_porcelain_z(output: str) -> tuple[str, ...]:
    """Parse NUL-delimited porcelain output including both sides of renames."""
    entries = output.split("\0")
    paths: set[str] = set()
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        status = entry[:2]
        path = entry[3:]
        if ("R" in status or "C" in status) and index < len(entries) and entries[index]:
            paths.add(entries[index])
            index += 1
        paths.add(path)
    return tuple(sorted(paths))


def staged_paths(root: Path) -> tuple[str, ...]:
    """Return paths represented by the Git index."""
    output = _git(root, "diff", "--cached", "--name-only", "-z")
    return parse_name_only_z(output)


def parse_name_only_z(output: str) -> tuple[str, ...]:
    """Parse NUL-delimited Git path output without platform reinterpretation."""
    return tuple(sorted(path for path in output.split("\0") if path))


def _git(root: Path, *arguments: str) -> str:
    """Run one read-only Git query and return its standard output."""
    result = subprocess.run(
        ("git", *arguments),
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise GitChangeError(result.stderr.strip() or "Git change query failed")
    return result.stdout
