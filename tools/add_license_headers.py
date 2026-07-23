#!/usr/bin/env python3
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

"""Normalize GPL headers across both package roots and repository Python files."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

COPYRIGHT_LINE = "#    Copyright (C) 2025  Artificial Sweetener and contributors"
LICENSE_LINES = (
    "#",
    "#    This program is free software: you can redistribute it and/or modify",
    "#    it under the terms of the GNU General Public License as published by",
    "#    the Free Software Foundation, either version 3 of the License, or",
    "#    (at your option) any later version.",
    "#",
    "#    This program is distributed in the hope that it will be useful,",
    "#    but WITHOUT ANY WARRANTY; without even the implied warranty of",
    "#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the",
    "#    GNU General Public License for more details.",
    "#",
    "#    You should have received a copy of the GNU General Public License",
    "#    along with this program.  If not, see <https://www.gnu.org/licenses/>.",
)
PRODUCT_HEADER = re.compile(r"^#\s{1,4}.*(?:QPane|CuteCanvas).*$")


def python_files() -> tuple[Path, ...]:
    """Return tracked and new non-ignored Python sources in deterministic order."""
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            "*.py",
            "*.pyi",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    excluded = {".package-smoke", ".venv", "build", "dist", "site-packages"}
    return tuple(
        sorted(
            path
            for path in {Path(value) for value in result.stdout.splitlines()}
            if not any(part in excluded for part in path.parts)
        )
    )


def _product_line(path: Path) -> str:
    """Return the canonical product line for one repository source."""
    normalized = path.as_posix()
    if normalized.startswith(("packages/cutecanvas/", "examples/demonstration/")):
        return "#    CuteCanvas - High-performance layered image editor"
    if normalized == "examples/cutecanvas_demo.py":
        return "#    CuteCanvas - High-performance layered image editor"
    if normalized.startswith(("packages/qpane/", "examples/qpane_demonstration/")):
        return "#    QPane - High-performance PySide6 image viewer"
    if normalized == "examples/qpane_demo.py":
        return "#    QPane - High-performance PySide6 image viewer"
    return "#    QPane + CuteCanvas - High-performance PySide6 rendering and editing"


def _header_span(lines: list[str]) -> tuple[int, int] | None:
    """Return the contiguous leading product-license comment span."""
    start = next(
        (index for index, line in enumerate(lines[:4]) if PRODUCT_HEADER.match(line)),
        None,
    )
    if start is None:
        return None
    end = start
    while end + 1 < len(lines) and lines[end + 1].startswith("#"):
        end += 1
    return start, end


def normalize_header(path: Path) -> bool:
    """Write one canonical header while retaining its product-specific first line."""
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    span = _header_span(lines)
    if span is None and "GNU General Public License" in content[:1200]:
        return False
    product_line = _product_line(path)
    canonical = [product_line, COPYRIGHT_LINE, *LICENSE_LINES]
    if span is None:
        insertion = 1 if lines and lines[0].startswith("#!") else 0
        updated = [*lines[:insertion], *canonical, "", *lines[insertion:]]
    else:
        updated = [*lines[: span[0]], *canonical, *lines[span[1] + 1 :]]
    normalized = "\n".join(updated).rstrip() + "\n"
    if normalized == content.replace("\r\n", "\n"):
        return False
    path.write_text(normalized, encoding="utf-8", newline="\n")
    return True


def main() -> None:
    """Normalize every repository Python header and report changed paths."""
    files = python_files()
    changed = 0
    for path in files:
        if path.is_file() and normalize_header(path):
            changed += 1
            print(f"Normalized header in {path}")
    print(f"Checked {len(files)} Python files; normalized {changed}.")


if __name__ == "__main__":
    main()
