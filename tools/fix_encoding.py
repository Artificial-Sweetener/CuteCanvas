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

"""Ensure all tracked repository text files are encoded in UTF-8.

Scans source, configuration, and documentation files and attempts to convert
any non-UTF-8 content (for example cp1252 or latin1) to UTF-8.
"""

import argparse
import subprocess
from pathlib import Path


def get_repository_text_files() -> tuple[Path, ...]:
    """Return tracked and new non-ignored source and documentation files."""
    try:
        # Use git ls-files to respect gitignore
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
                "*.toml",
                "*.json",
                "*.md",
                "*.yml",
                "*.yaml",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return tuple(sorted(Path(value) for value in result.stdout.splitlines()))
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("Unable to enumerate repository text files") from exc


def ensure_utf8(file_path: Path, *, write: bool) -> bool:
    """Check one file and optionally convert recoverable content to UTF-8."""
    try:
        # Try reading as UTF-8 first
        file_path.read_text(encoding="utf-8")
        return True
    except UnicodeDecodeError:
        print(f"Found non-UTF-8 file: {file_path}")
    # If UTF-8 failed, try common fallbacks
    encodings = ["cp1252", "latin1", "utf-16"]
    content: str | None = None
    for enc in encodings:
        try:
            content = file_path.read_text(encoding=enc)
            print(f"  - Successfully read as {enc}. Converting to UTF-8...")
            break
        except UnicodeDecodeError:
            continue
    if content is not None and write:
        file_path.write_text(content, encoding="utf-8")
        print(f"  - Fixed {file_path}")
        return True
    print(f"  - FAILED UTF-8 check for {file_path}.")
    return False


def main() -> None:
    """Check or repair repository text encoding."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    print("Scanning for encoding issues...")
    files = get_repository_text_files()
    success = True
    for file_path in files:
        if file_path.exists():
            success = ensure_utf8(file_path, write=not arguments.check) and success
    print("Done.")
    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
