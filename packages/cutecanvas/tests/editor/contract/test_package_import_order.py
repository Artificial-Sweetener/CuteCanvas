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

"""Cold-process import-order contracts for public CuteCanvas namespaces."""

from __future__ import annotations

import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "statement",
    (
        "from cutecanvas.painting import BrushCompositor; "
        "from cutecanvas.coverage import CoverageDocumentEvaluator",
        "from cutecanvas.coverage import CoverageDocumentEvaluator; "
        "from cutecanvas.painting import BrushCompositor",
    ),
)
def test_painting_and_coverage_import_in_either_order(statement: str) -> None:
    """Public painting and coverage owners must not rely on warmed modules."""
    result = subprocess.run(
        [sys.executable, "-c", statement],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
