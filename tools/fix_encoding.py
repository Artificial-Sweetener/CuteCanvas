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

"""Ensure all tracked Python files are encoded in UTF-8.

Scans the repository for Python files and attempts to convert any non-UTF-8
files (e.g. cp1252, latin1) to UTF-8.
"""

import subprocess
import sys
from pathlib import Path


def get_tracked_python_files():
    """Return a list of all Python files tracked by git."""
    try:
        # Use git ls-files to respect gitignore
        result = subprocess.run(
            ["git", "ls-files", "*.py"], capture_output=True, text=True, check=True
        )
        return [Path(p) for p in result.stdout.splitlines()]
    except subprocess.CalledProcessError as e:
        print(f"Error running git ls-files: {e}")
        sys.exit(1)


def ensure_utf8(file_path):
    """Check and convert the file to UTF-8 if necessary."""
    try:
        # Try reading as UTF-8 first
        content = file_path.read_text(encoding="utf-8")
        # If successful, we just write it back to ensure consistent line endings (LF)
        # if that's desired, or just pass.
        # Let's write it back to enforce the encoding if it was somehow mixed.
        return
    except UnicodeDecodeError:
        print(f"Found non-UTF-8 file: {file_path}")
    # If UTF-8 failed, try common fallbacks
    encodings = ["cp1252", "latin1", "utf-16"]
    content = None
    for enc in encodings:
        try:
            content = file_path.read_text(encoding=enc)
            print(f"  - Successfully read as {enc}. Converting to UTF-8...")
            break
        except UnicodeDecodeError:
            continue
    if content is not None:
        file_path.write_text(content, encoding="utf-8")
        print(f"  - Fixed {file_path}")
    else:
        print(f"  - FAILED to recover {file_path}. Unknown encoding.")


def main():
    print("Scanning for encoding issues...")
    files = get_tracked_python_files()
    for file_path in files:
        if file_path.exists():
            ensure_utf8(file_path)
    print("Done.")


if __name__ == "__main__":
    main()
