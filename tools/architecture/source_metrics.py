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
"""Own stable source measurements used by architecture state."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path


def production_line_count(path: Path) -> int:
    """Count nonblank physical lines that are not comment-only lines."""
    comment_prefixes = ("//", "/*", "*", "*/") if path.suffix == ".rs" else ("#",)
    return sum(
        1
        for line in normalized_source(path).splitlines()
        if line.strip() and not line.lstrip().startswith(comment_prefixes)
    )


def source_fingerprint(root: Path, paths: Iterable[str]) -> str:
    """Return a platform-stable fingerprint for exact repository paths."""
    digest = hashlib.sha256()
    for relative_path in sorted(paths):
        normalized_path = relative_path.replace("\\", "/")
        digest.update(normalized_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(normalized_source(root / normalized_path).encode("utf-8"))
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def normalized_source(path: Path) -> str:
    """Read UTF-8 source with canonical newlines for cross-platform identity."""
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
