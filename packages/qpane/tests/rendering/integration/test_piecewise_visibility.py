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

"""Conservative source-demand proof for bounded piecewise mappings."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QTransform
from qpane.rendering.panel_mapping import PiecewisePanelMapping
from qpane.rendering.projective_visibility import visible_source_rect
from qpane.sdk.scene import PiecewiseLayerTransform


def test_piecewise_mapping_demands_every_visible_source_patch() -> None:
    """Patch-wise visibility must not discard any contributing source region."""
    mapping = PiecewiseLayerTransform(
        (
            QPointF(640.0, 200.0),
            QPointF(1440.0, 200.0),
            QPointF(1440.0, 600.0),
            QPointF(1440.0, 1000.0),
            QPointF(640.0, 1000.0),
        ),
        (
            QPointF(640.0, 200.0),
            QPointF(1440.0, 200.0),
            QPointF(1300.0, 600.0),
            QPointF(1440.0, 1000.0),
            QPointF(640.0, 1000.0),
        ),
    )
    viewport = QTransform.fromScale(0.316279, 0.316279)
    viewport.translate(-640.0, 707.536765)
    panel_mapping = PiecewisePanelMapping.from_layer_mapping(mapping, viewport)

    visible = visible_source_rect(
        panel_mapping,
        QRectF(-64.0, -64.0, 1216.0, 1031.0),
        QRectF(0.0, 0.0, 3440.0, 1440.0),
    )

    assert visible == QRectF(640.0, 200.0, 800.0, 800.0)
