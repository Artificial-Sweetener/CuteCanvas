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

"""Abuse mounted responsive grids across DPR, starvation, and topology changes."""

from __future__ import annotations

import uuid
from itertools import pairwise

from cutecanvas import (
    CanvasDocument,
    CanvasWorkspace,
    CuteCanvas,
    ResponsiveGridPacking,
    ResponsiveGridPolicy,
    ResponsiveGridSnapshot,
)
from cutecanvas.presentation.grid_surface import ResponsiveCanvasGrid
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage


def test_fractional_dpr_grid_keeps_equal_tiles_and_physical_gutters(
    qapp,
    monkeypatch,
) -> None:
    """Keep every row and column stable when logical pixels map to 1.5 physical pixels."""

    monkeypatch.setattr(
        ResponsiveCanvasGrid,
        "devicePixelRatioF",
        lambda _self: 1.5,
    )
    document, identifiers = _document(("red", "green", "blue"))
    workspace = CanvasWorkspace(document=document, features=())
    policy = ResponsiveGridPolicy(
        packing=ResponsiveGridPacking.NATIVE_TILES,
        native_tile_viewport_gap=2.0,
    )
    try:
        workspace.resize(503, 311)
        workspace.setGridPresentation(identifiers, policy=policy)
        workspace.show()
        qapp.processEvents()

        for width in range(503, 511):
            workspace.resize(width, 311)
            qapp.processEvents()
            snapshot = workspace.gridSnapshot()
            assert snapshot is not None
            assert snapshot.device_pixel_ratio == 1.5
            canvases = _canvases(workspace, snapshot)
            geometries = [canvas.parentWidget().geometry() for canvas in canvases]
            assert (
                len({(geometry.width(), geometry.height()) for geometry in geometries})
                == 1
            )
            horizontal_gaps = [
                second.x() - first.right() - 1
                for first, second in pairwise(geometries)
                if first.y() == second.y()
            ]
            assert not horizontal_gaps or set(horizontal_gaps) == {2}
            assert all(canvas.currentZoom() > 0.0 for canvas in canvases)
    finally:
        workspace.close()
        document.close()
        qapp.processEvents()


def test_width_starved_grid_never_overlaps_or_escapes_viewport(qapp) -> None:
    """Degrade tiny layouts to bounded non-overlapping target rectangles."""

    document, identifiers = _document(("red", "green", "blue", "yellow"))
    workspace = CanvasWorkspace(document=document, features=())
    policy = ResponsiveGridPolicy(
        packing=ResponsiveGridPacking.NATIVE_TILES,
        native_tile_viewport_gap=2.0,
    )
    try:
        workspace.resize(7, 5)
        workspace.setGridPresentation(identifiers, policy=policy)
        workspace.show()
        qapp.processEvents()
        snapshot = workspace.gridSnapshot()
        assert snapshot is not None
        geometries = [
            canvas.parentWidget().geometry()
            for canvas in _canvases(workspace, snapshot)
        ]

        assert all(workspace.rect().contains(geometry) for geometry in geometries)
        assert all(
            geometry.width() >= 1 and geometry.height() >= 1 for geometry in geometries
        )
        assert all(
            not first.intersects(second)
            for index, first in enumerate(geometries)
            for second in geometries[index + 1 :]
        )
    finally:
        workspace.close()
        document.close()
        qapp.processEvents()


def test_grid_pixels_settle_after_repeated_topology_changes(qapp) -> None:
    """Keep each source in its assigned tile after hostile wide/tall resize cycling."""

    colors = ("red", "green", "blue")
    document, identifiers = _document(colors)
    workspace = CanvasWorkspace(document=document, features=())
    policy = ResponsiveGridPolicy(
        packing=ResponsiveGridPacking.NATIVE_TILES,
        native_tile_viewport_gap=2.0,
    )
    try:
        workspace.setGridPresentation(identifiers, policy=policy)
        workspace.show()
        for size in (
            QSize(720, 240),
            QSize(280, 620),
            QSize(721, 241),
            QSize(279, 619),
            QSize(720, 240),
        ):
            workspace.resize(size)
            qapp.processEvents()
            workspace.grab()
            qapp.processEvents()
        rendered = workspace.grab().toImage()
        snapshot = workspace.gridSnapshot()
        assert snapshot is not None

        for frame, color_name in zip(snapshot.frames, colors, strict=True):
            canvas = workspace.canvasFor(frame.target_id)
            assert canvas is not None
            center = canvas.mapTo(workspace, canvas.rect().center())
            assert rendered.pixelColor(center) == QColor(color_name)
    finally:
        workspace.close()
        document.close()
        qapp.processEvents()


def _document(
    colors: tuple[str, ...],
) -> tuple[CanvasDocument, tuple[uuid.UUID, ...]]:
    """Create equal-size colored image compositions."""

    document = CanvasDocument()
    identifiers = tuple(
        document.create_composition_from_image(
            _image(QSize(120, 80), QColor(color)),
            title=color,
        )
        for color in colors
    )
    return document, identifiers


def _image(size: QSize, color: QColor) -> QImage:
    """Return one opaque tile source."""

    image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(color)
    return image


def _canvases(
    workspace: CanvasWorkspace,
    snapshot: ResponsiveGridSnapshot,
) -> tuple[CuteCanvas, ...]:
    """Return all mounted target canvases from a responsive snapshot."""

    return tuple(
        workspace.canvasFor(frame.target_id)
        for frame in snapshot.frames
        if workspace.canvasFor(frame.target_id) is not None
    )
