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
"""Run repository architecture checks or calculate an assessed fingerprint."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from architecture.checker import run
from architecture.snapshot import repository_snapshot
from architecture.source_metrics import source_fingerprint


def main() -> int:
    """Validate current architecture state or print a source fingerprint."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--staged",
        action="store_true",
        help="validate the exact Git index instead of the worktree",
    )
    parser.add_argument(
        "--fingerprint",
        nargs="+",
        metavar="PATH",
        help="print the architecture fingerprint for exact repository paths",
    )
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if arguments.fingerprint:
        paths = tuple(path.replace("\\", "/") for path in arguments.fingerprint)
        with repository_snapshot(root, staged=arguments.staged) as snapshot:
            print(source_fingerprint(snapshot, paths))
        return 0
    run(root, staged=arguments.staged)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
