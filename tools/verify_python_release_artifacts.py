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
"""Verify exact Python distribution artifacts before trusted publication."""

from __future__ import annotations

import argparse
from pathlib import Path

from tools.release.artifact_validation import validate_artifacts
from tools.release.products import format_version, release_from_tag


def run(tag: str, distribution: Path) -> None:
    """Validate one tag-selected distribution directory."""
    product, version = release_from_tag(tag)
    version_text = format_version(version)
    errors = validate_artifacts(product, version_text, distribution)
    if errors:
        raise RuntimeError("\n".join(errors))
    print(
        f"SUCCESS: {distribution} contains release-ready "
        f"{product.name}=={version_text} artifacts."
    )


def main() -> None:
    """Parse the tag and distribution path supplied by publishing CI."""
    parser = argparse.ArgumentParser()
    parser.add_argument("tag", help="Product-prefixed Git release tag")
    parser.add_argument("distribution", type=Path, help="Built artifact directory")
    arguments = parser.parse_args()
    try:
        run(arguments.tag, arguments.distribution)
    except (RuntimeError, ValueError) as error:
        parser.exit(1, f"ERROR: {error}\n")


if __name__ == "__main__":
    main()
