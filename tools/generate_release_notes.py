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
"""Write package-scoped GitHub release notes for one product tag."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.release.notes import generate_release_notes
from tools.release.products import release_from_tag


def run(tag: str, output: Path) -> None:
    """Generate and write release notes for one product tag."""
    product, version = release_from_tag(tag)
    notes = generate_release_notes(_ROOT, product, version, tag)
    output.write_text(notes, encoding="utf-8", newline="\n")
    print(f"SUCCESS: wrote {product.display_name} release notes to {output}.")


def main() -> None:
    """Parse the tag and output path supplied by release CI."""
    parser = argparse.ArgumentParser()
    parser.add_argument("tag", help="Product-prefixed Git release tag")
    parser.add_argument("output", type=Path, help="Markdown output path")
    arguments = parser.parse_args()
    run(arguments.tag, arguments.output)


if __name__ == "__main__":
    main()
