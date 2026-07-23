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
"""Semantic vector geometry creation shared by coverage-authoring tools."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor
from qpane.sdk.scene import LayerTransform
from qpane.sdk.vector import (
    VectorObject,
    VectorObjectKind,
    VectorPathCommand,
    VectorPathCommandKind,
    VectorShapeKind,
    VectorStyle,
)


class CoverageGeometryFactory:
    """Create fill-only semantic vector objects for retained coverage."""

    def rectangle(self, rectangle: QRectF) -> VectorObject:
        """Return one retained parametric rectangle."""
        return self._shape(rectangle, VectorShapeKind.RECTANGLE)

    def ellipse(self, rectangle: QRectF) -> VectorObject:
        """Return one retained parametric ellipse."""
        return self._shape(rectangle, VectorShapeKind.ELLIPSE)

    def lasso(self, points: Sequence[QPointF]) -> VectorObject:
        """Return one closed retained polygon path."""
        detached = tuple(QPointF(point) for point in points)
        if len(detached) < 3:
            raise ValueError("lasso coverage requires at least three points")
        left = min(point.x() for point in detached)
        top = min(point.y() for point in detached)
        right = max(point.x() for point in detached)
        bottom = max(point.y() for point in detached)
        commands = [
            VectorPathCommand(VectorPathCommandKind.MOVE, (detached[0],)),
            *(
                VectorPathCommand(VectorPathCommandKind.LINE, (point,))
                for point in detached[1:]
            ),
            VectorPathCommand(VectorPathCommandKind.CLOSE),
        ]
        return VectorObject(
            object_id=uuid.uuid4(),
            kind=VectorObjectKind.PATH,
            local_bounds=(left, top, right - left, bottom - top),
            transform=LayerTransform(),
            style=_coverage_style(),
            path=tuple(commands),
        )

    @staticmethod
    def _shape(rectangle: QRectF, kind: VectorShapeKind) -> VectorObject:
        """Return one positive-area parametric coverage shape."""
        bounds = rectangle.normalized()
        if bounds.isEmpty():
            raise ValueError("coverage shape must have positive area")
        return VectorObject(
            object_id=uuid.uuid4(),
            kind=VectorObjectKind.SHAPE,
            local_bounds=(bounds.x(), bounds.y(), bounds.width(), bounds.height()),
            transform=LayerTransform(),
            style=_coverage_style(),
            shape_kind=kind,
        )


def _coverage_style() -> VectorStyle:
    """Return the canonical opaque fill-only coverage style."""
    return VectorStyle(fill=QColor(255, 255, 255), stroke=None)
