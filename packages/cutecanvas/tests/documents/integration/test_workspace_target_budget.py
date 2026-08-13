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

"""Verify bounded role-target renderer retention in large workspaces."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QRectF

from cutecanvas import CanvasDocument, CanvasWorkspace, CuteCanvas


def test_workspace_bounds_inactive_renderers_after_many_target_reflow(qapp) -> None:
    """Keep active targets plus only the configured hidden-renderer budget."""

    document = CanvasDocument()
    identifiers = tuple(
        document.create_composition(
            QRectF(0.0, 0.0, 640.0 + index, 480.0),
            title=f"Target {index}",
        )
        for index in range(48)
    )
    inactive_capacity = 5
    workspace = CanvasWorkspace(
        document=document,
        features=(),
        retained_target_capacity=inactive_capacity,
    )
    try:
        workspace.resize(1200, 800)
        workspace.setGridPresentation(identifiers)
        assert len(workspace.findChildren(CuteCanvas)) == len(identifiers)

        workspace.setSinglePresentation(identifiers[0])
        qapp.processEvents()
        assert len(workspace.findChildren(CuteCanvas)) <= inactive_capacity + 1

        workspace.setComparisonPresentation(identifiers[0], identifiers[1])
        qapp.processEvents()
        assert len(workspace.findChildren(CuteCanvas)) <= inactive_capacity
    finally:
        workspace.close()
        document.close()
        qapp.processEvents()


def test_workspace_rejects_negative_inactive_renderer_budget() -> None:
    """Reject invalid capacity before constructing any renderer owners."""

    document = CanvasDocument()
    try:
        with pytest.raises(
            ValueError,
            match="inactive_capacity must not be negative",
        ):
            CanvasWorkspace(document=document, retained_target_capacity=-1)
    finally:
        document.close()
