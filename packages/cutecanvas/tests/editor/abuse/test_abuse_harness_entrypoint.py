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

"""Protect the standalone mounted-abuse command contract."""

from __future__ import annotations

import os
import subprocess
import sys

from cutecanvas_test_support.repository import repository_root

_REPOSITORY_ROOT = repository_root()


def test_abuse_harness_bootstraps_monorepo_packages() -> None:
    """Launch the harness without pytest's configured package source paths."""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(
        _REPOSITORY_ROOT / "packages" / "cutecanvas" / "tests"
    )
    result = subprocess.run(
        [sys.executable, "-m", "cutecanvas_test_support.harness", "--help"],
        cwd=_REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Abuse a real mounted CuteCanvas" in result.stdout
