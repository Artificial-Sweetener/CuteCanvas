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

"""Immutable affine patches for bounded layer mappings."""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QPointF

from .affine import LayerTransform
from .piecewise_topology import (
    finite_triangle,
    scaled_epsilon,
    triangle_area,
    triangle_contains,
)


@dataclass(frozen=True, slots=True)
class TriangularLayerMappingPatch:
    """Map one source triangle into its corresponding target triangle."""

    source: tuple[QPointF, QPointF, QPointF]
    target: tuple[QPointF, QPointF, QPointF]
    transform: LayerTransform = field(init=False)

    def __post_init__(self) -> None:
        """Detach triangles and solve their exact affine correspondence."""
        source = finite_triangle(self.source, name="source")
        target = finite_triangle(self.target, name="target")
        if abs(triangle_area(source)) <= scaled_epsilon(source):
            raise ValueError("piecewise source patch must be nondegenerate")
        if abs(triangle_area(target)) <= scaled_epsilon(target):
            raise ValueError("piecewise target patch must be nondegenerate")
        transform = _triangle_transform(source, target)
        if not transform.is_invertible:
            raise ValueError("piecewise patch transform must be invertible")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "transform", transform)

    def contains_source(self, point: QPointF) -> bool:
        """Return whether a point belongs to this closed source triangle."""
        return triangle_contains(self.source, point)

    def contains_target(self, point: QPointF) -> bool:
        """Return whether a point belongs to this closed target triangle."""
        return triangle_contains(self.target, point)


def _triangle_transform(
    source: tuple[QPointF, QPointF, QPointF],
    target: tuple[QPointF, QPointF, QPointF],
) -> LayerTransform:
    """Solve one affine transform from corresponding triangle vertices."""
    source_u = source[1] - source[0]
    source_v = source[2] - source[0]
    target_u = target[1] - target[0]
    target_v = target[2] - target[0]
    determinant = source_u.x() * source_v.y() - source_u.y() * source_v.x()
    if determinant == 0.0:
        raise ValueError("piecewise triangle does not define an affine mapping")
    m11 = (target_u.x() * source_v.y() - target_v.x() * source_u.y()) / determinant
    m21 = (target_v.x() * source_u.x() - target_u.x() * source_v.x()) / determinant
    m12 = (target_u.y() * source_v.y() - target_v.y() * source_u.y()) / determinant
    m22 = (target_v.y() * source_u.x() - target_u.y() * source_v.x()) / determinant
    return LayerTransform(
        m11=m11,
        m12=m12,
        m21=m21,
        m22=m22,
        dx=target[0].x() - m11 * source[0].x() - m21 * source[0].y(),
        dy=target[0].y() - m12 * source[0].x() - m22 * source[0].y(),
    )


__all__ = ["TriangularLayerMappingPatch"]
