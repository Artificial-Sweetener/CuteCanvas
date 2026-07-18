#!/usr/bin/env python3
#    QPane - High-performance PySide6 image viewer
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
"""Add or update license headers in all tracked Python files.

Scans the git repository for .py and .pyi files and ensures they start with
the correct license header, updating old versions if found.
"""

import re
import subprocess
import sys
from pathlib import Path

HEADER_PREFIX = "#    QPane - High-performance PySide6 image viewer"
COPYRIGHT_LINE = "#    Copyright (C) 2025  Artificial Sweetener and contributors"
LICENSE_BODY = """#
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
"""

COPYRIGHT_VARIANT_PATTERN = re.compile(
    r"#\s+Copyright \(C\)\s+2025\s+Artificial Sweetener(?:\s+and\s+contributors)*"
)
NEW_HEADER_START = f"{HEADER_PREFIX}\n{COPYRIGHT_LINE}"
FULL_NEW_HEADER = f"{NEW_HEADER_START}\n{LICENSE_BODY}"
HEADER_END_MARKER = (
    "#    along with this program.  If not, see <https://www.gnu.org/licenses/>."
)


def _normalize_header_block(lines: list[str]) -> list[str] | None:
    header_start = None
    header_end = None
    for idx, line in enumerate(lines):
        if line.rstrip("\n") == HEADER_PREFIX:
            header_start = idx
            break
    if header_start is None:
        return None
    for idx in range(header_start, len(lines)):
        candidate = lines[idx].rstrip("\n")
        if candidate == HEADER_END_MARKER:
            header_end = idx
            continue
        if candidate and not candidate.startswith("#"):
            break
    if header_end is None or header_end < header_start:
        return None
    existing_block = "".join(lines[header_start : header_end + 1]).rstrip("\n")
    canonical_block = FULL_NEW_HEADER.rstrip("\n")
    if existing_block == canonical_block:
        return None
    normalized = FULL_NEW_HEADER.splitlines()
    return (
        lines[:header_start]
        + [line + "\n" for line in normalized]
        + lines[header_end + 1 :]
    )


def get_tracked_python_files():
    try:
        # Use git ls-files to respect gitignore and only get tracked files
        # Get both .py and .pyi files
        result_py = subprocess.run(
            ["git", "ls-files", "*.py"], capture_output=True, text=True, check=True
        )
        result_pyi = subprocess.run(
            ["git", "ls-files", "*.pyi"], capture_output=True, text=True, check=True
        )
        files = set()
        if result_py.stdout:
            files.update(Path(p) for p in result_py.stdout.splitlines())
        if result_pyi.stdout:
            files.update(Path(p) for p in result_pyi.stdout.splitlines())
        return sorted(files)
    except subprocess.CalledProcessError as e:
        print(f"Error running git ls-files: {e}")
        sys.exit(1)


def update_header(file_path):
    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        print(f"Skipping {file_path}: Unable to read (encoding issue)")
        return
    # 1. Normalize any copyright line variants (missing or duplicated contributors)
    match = COPYRIGHT_VARIANT_PATTERN.search(content)
    if match and match.group(0) != COPYRIGHT_LINE:
        new_content = (
            f"{content[: match.start()]}{COPYRIGHT_LINE}{content[match.end():]}"
        )
        file_path.write_text(new_content, encoding="utf-8")
        print(f"Updated header in {file_path}")
        return
    lines = content.splitlines(keepends=True)
    normalized_lines = _normalize_header_block(lines)
    if normalized_lines is not None:
        file_path.write_text("".join(normalized_lines), encoding="utf-8")
        print(f"Normalized header in {file_path}")
        return
    # 2. Check if the new header is already there
    if NEW_HEADER_START in content:
        # Already up to date
        return
    # 3. If no header found (or at least not the ones we know), add the new one
    # Avoid double-adding if some other variation exists
    if "GNU General Public License" in content[:1000]:
        print(f"Skipping {file_path}: Unknown license header already present")
        return
    insert_idx = 0
    # Handle Shebangs (must be first line)
    if lines and lines[0].startswith("#!"):
        insert_idx += 1
    # Handle Encoding declarations (must be first or second line)
    if (
        len(lines) > insert_idx
        and lines[insert_idx].startswith("#")
        and "coding" in lines[insert_idx]
    ):
        insert_idx += 1
    # Insert header
    new_lines = lines[:insert_idx] + [FULL_NEW_HEADER + "\n"] + lines[insert_idx:]
    new_content = "".join(new_lines)
    file_path.write_text(new_content, encoding="utf-8")
    print(f"Added header to {file_path}")


def main():
    files = get_tracked_python_files()
    print(f"Found {len(files)} tracked Python files.")
    for file_path in files:
        if not file_path.exists():
            continue
        update_header(file_path)


if __name__ == "__main__":
    main()
