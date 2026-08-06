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

"""Normalize GPL headers across repository Python and Rust source files."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

COPYRIGHT_TEXT = "    Copyright (C) 2025  Artificial Sweetener and contributors"
LICENSE_TEXT = (
    "",
    "    This program is free software: you can redistribute it and/or modify",
    "    it under the terms of the GNU General Public License as published by",
    "    the Free Software Foundation, either version 3 of the License, or",
    "    (at your option) any later version.",
    "",
    "    This program is distributed in the hope that it will be useful,",
    "    but WITHOUT ANY WARRANTY; without even the implied warranty of",
    "    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the",
    "    GNU General Public License for more details.",
    "",
    "    You should have received a copy of the GNU General Public License",
    "    along with this program.  If not, see <https://www.gnu.org/licenses/>.",
)
PRODUCT_HEADER = re.compile(r"^(?:#|//)\s{1,4}.*(?:Ferrastra|QPane|CuteCanvas).*$")


def source_files() -> tuple[Path, ...]:
    """Return tracked and new non-ignored Python and Rust sources."""
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
            "*.rs",
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


def _product_text(path: Path) -> str:
    """Return the canonical product text for one repository source."""
    normalized = path.as_posix()
    if normalized.startswith(("packages/ferrastra/", "crates/ferrastra-")):
        return "    Ferrastra - CPU-first native graphics product engine"
    if normalized == "packages/ferrastra/examples/ferrastra_demo.py":
        return "    Ferrastra - CPU-first native graphics product engine"
    if normalized.startswith("tools/architecture/") or "ferrastra" in path.name.lower():
        return (
            "    QPane + CuteCanvas + Ferrastra - Native graphics architecture tooling"
        )
    if normalized.startswith(
        ("packages/cutecanvas/", "packages/cutecanvas/examples/demonstration/")
    ):
        return "    CuteCanvas - High-performance layered image editor"
    if normalized == "packages/cutecanvas/examples/cutecanvas_demo.py":
        return "    CuteCanvas - High-performance layered image editor"
    if normalized.startswith(
        ("packages/qpane/", "packages/qpane/examples/qpane_demonstration/")
    ):
        return "    QPane - High-performance PySide6 image viewer"
    if normalized == "packages/qpane/examples/qpane_demo.py":
        return "    QPane - High-performance PySide6 image viewer"
    return "    QPane + CuteCanvas - High-performance PySide6 rendering and editing"


def _header_span(lines: list[str], prefix: str) -> tuple[int, int] | None:
    """Return the contiguous leading product-license comment span."""
    start = next(
        (index for index, line in enumerate(lines[:4]) if PRODUCT_HEADER.match(line)),
        None,
    )
    if start is None:
        return None
    end = start
    while end + 1 < len(lines) and lines[end + 1].startswith(prefix):
        end += 1
    return start, end


def normalize_header(path: Path, *, write: bool = True) -> bool:
    """Write one canonical header while retaining its product-specific first line."""
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    prefix = "//" if path.suffix == ".rs" else "#"
    span = _header_span(lines, prefix)
    if span is None and "GNU General Public License" in content[:1200]:
        return False
    canonical = [
        f"{prefix}{_product_text(path)}",
        f"{prefix}{COPYRIGHT_TEXT}",
        *(f"{prefix}{line}" for line in LICENSE_TEXT),
    ]
    if span is None:
        insertion = 1 if lines and lines[0].startswith("#!") else 0
        updated = [*lines[:insertion], *canonical, "", *lines[insertion:]]
    else:
        updated = [*lines[: span[0]], *canonical, *lines[span[1] + 1 :]]
    normalized = "\n".join(updated).rstrip() + "\n"
    if normalized == content.replace("\r\n", "\n"):
        return False
    if write:
        path.write_text(normalized, encoding="utf-8", newline="\n")
    return True


def main() -> None:
    """Normalize or check every repository source header."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    files = source_files()
    changed = 0
    for path in files:
        if path.is_file() and normalize_header(path, write=not arguments.check):
            changed += 1
            action = (
                "Needs header normalization" if arguments.check else "Normalized header"
            )
            print(f"{action} in {path}")
    print(f"Checked {len(files)} source files; found {changed} noncanonical headers.")
    if arguments.check and changed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
