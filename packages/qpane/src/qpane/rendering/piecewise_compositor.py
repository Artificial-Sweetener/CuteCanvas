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

"""Composite one bounded piecewise layer without exposing patch boundaries."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Protocol

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPainterPathStroker

from ..scene.render_plan import SceneRenderItem
from .panel_mapping import PiecewisePanelMapping


class _LayerIsolation(Protocol):
    """Describe the isolated surface operation required by this owner."""

    def composite(
        self,
        painter: QPainter,
        *,
        opacity: float,
        paint_layer: Callable[[QPainter], None],
    ) -> None:
        """Render one layer independently and composite it once."""


def draw_piecewise_item(
    painter: QPainter,
    item: SceneRenderItem,
    *,
    isolation: _LayerIsolation,
    panel_bounds: QRectF,
    panel_clips: tuple[QRectF, ...] | None,
    draw_patch: Callable[
        [QPainter, SceneRenderItem, tuple[QRectF, ...] | None],
        None,
    ],
) -> bool:
    """Draw watertight affine patches and return whether ``item`` was piecewise."""
    mapping = item.transform
    if not isinstance(mapping, PiecewisePanelMapping):
        return False

    patch_descriptor = replace(item.descriptor, opacity=1.0)

    def paint_layer(layer_painter: QPainter) -> None:
        """Replace each shared-edge pixel before applying layer opacity once."""
        layer_painter.setClipPath(
            mapping.panel_path,
            Qt.ClipOperation.IntersectClip,
        )
        layer_painter.setCompositionMode(QPainter.CompositionMode_Source)
        overlap = 1.0 / max(float(layer_painter.device().devicePixelRatioF()), 1.0)
        for patch in mapping.patches:
            expanded_panel_path = _expanded_path(patch.panel_path, overlap)
            layer_painter.save()
            try:
                layer_painter.setClipPath(
                    expanded_panel_path,
                    Qt.ClipOperation.IntersectClip,
                )
                draw_patch(
                    layer_painter,
                    replace(
                        item,
                        descriptor=patch_descriptor,
                        transform=patch.transform,
                        mapping_clip_path=None,
                    ),
                    _bounded_panel_clips(
                        panel_clips,
                        patch.panel_path.boundingRect(),
                    ),
                )
            finally:
                layer_painter.restore()

    painter.save()
    try:
        painter.setClipRect(panel_bounds, Qt.ClipOperation.IntersectClip)
        isolation.composite(
            painter,
            opacity=item.descriptor.opacity,
            paint_layer=paint_layer,
        )
    finally:
        painter.restore()
    return True


def _bounded_panel_clips(
    panel_clips: tuple[QRectF, ...] | None,
    patch_bounds: QRectF,
) -> tuple[QRectF, ...] | None:
    """Confine repair demand to the finite domain of one projective patch."""
    if panel_clips is None:
        return None
    return tuple(
        bounded
        for panel_clip in panel_clips
        if not (bounded := panel_clip.intersected(patch_bounds)).isEmpty()
    )


def _expanded_path(path: QPainterPath, radius: float) -> QPainterPath:
    """Expand one panel patch enough to make shared device pixels watertight."""
    stroker = QPainterPathStroker()
    stroker.setWidth(radius * 2.0)
    stroker.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    return path.united(stroker.createStroke(path))


__all__ = ["draw_piecewise_item"]
