#    CuteCanvas - High-performance layered image editor
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

"""Verify comparison panning through the native Windows backing store."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from cutecanvas_test_support.harness.timing import INTERACTIVE_PERFORMANCE
from cutecanvas_test_support.repository import repository_root

_RUN_NATIVE_DESKTOP_TESTS = (
    os.environ.get("QPANE_RUN_NATIVE_DESKTOP_TESTS", "").strip() == "1"
)


@INTERACTIVE_PERFORMANCE
@pytest.mark.skipif(
    sys.platform != "win32" or not _RUN_NATIVE_DESKTOP_TESTS,
    reason="set QPANE_RUN_NATIVE_DESKTOP_TESTS=1 to allow a visible desktop probe",
)
def test_native_comparison_pan_matches_full_redraw(tmp_path: Path) -> None:
    """Require hostile native comparison panning to retain canonical pixels."""
    root = repository_root()
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "windows"
    python_paths = (
        root,
        root / "packages" / "qpane" / "src",
        root / "packages" / "cutecanvas" / "src",
        root / "packages" / "cutecanvas" / "tests",
    )
    environment["PYTHONPATH"] = os.pathsep.join(str(path) for path in python_paths)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "cutecanvas_test_support.harness_tools.comparison_pan_abuse_harness",
            "--artifact-root",
            str(tmp_path),
            "--allow-desktop-window",
        ],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
        creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS,
    )

    assert completed.returncode == 0, {
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "artifacts": str(tmp_path),
    }
