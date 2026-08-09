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

"""Immutable bounded piecewise geometry for source-neutral layer mapping."""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRect, QRectF
from PySide6.QtGui import QPainterPath, QPolygonF

from .affine import LayerTransform
from .model import LayerPlacement
from .piecewise_patches import TriangularLayerMappingPatch
from .piecewise_topology import (
    bounding_rect,
    finite_boundary,
    finite_point,
    triangulate_boundaries,
    validate_simple_boundary,
)
from .projective import ProjectiveLayerTransform
from .raster import RasterBounds


@dataclass(frozen=True, slots=True)
class PiecewiseLayerTransform:
    """Map one finite source cage through bounded continuous patches."""

    source_boundary: tuple[QPointF, ...]
    target_boundary: tuple[QPointF, ...]
    patches: tuple[TriangularLayerMappingPatch, ...] = field(
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        """Validate matching simple boundaries and build bounded patches."""
        source = finite_boundary(self.source_boundary, name="source")
        target = finite_boundary(self.target_boundary, name="target")
        if len(source) != len(target):
            raise ValueError("piecewise boundaries must have the same vertex count")
        source_winding = validate_simple_boundary(source, name="source")
        target_winding = validate_simple_boundary(target, name="target")
        if source_winding != target_winding:
            raise ValueError("piecewise boundaries must preserve winding")
        triangles = triangulate_boundaries(source, target, source_winding)
        patches = tuple(
            TriangularLayerMappingPatch(
                (
                    source[triangle[0]],
                    source[triangle[1]],
                    source[triangle[2]],
                ),
                (
                    target[triangle[0]],
                    target[triangle[1]],
                    target[triangle[2]],
                ),
            )
            for triangle in triangles
        )
        object.__setattr__(self, "source_boundary", source)
        object.__setattr__(self, "target_boundary", target)
        object.__setattr__(self, "patches", patches)

    @classmethod
    def _from_patches(
        cls,
        source_boundary: tuple[QPointF, ...],
        target_boundary: tuple[QPointF, ...],
        patches: tuple[TriangularLayerMappingPatch, ...],
    ) -> PiecewiseLayerTransform:
        """Create a mapping from already validated connected patches."""
        if not patches:
            raise ValueError("piecewise mapping requires at least one patch")
        instance = object.__new__(cls)
        object.__setattr__(instance, "source_boundary", source_boundary)
        object.__setattr__(instance, "target_boundary", target_boundary)
        object.__setattr__(instance, "patches", patches)
        return instance

    @property
    def is_invertible(self) -> bool:
        """Return whether every deterministic patch has an affine inverse."""
        return all(patch.transform.is_invertible for patch in self.patches)

    def map_point(self, point: QPointF) -> QPointF:
        """Map one point inside the finite source boundary."""
        local = finite_point(point, name="piecewise input")
        patch = next(
            (
                candidate
                for candidate in self.patches
                if candidate.contains_source(local)
            ),
            None,
        )
        if patch is None:
            raise ValueError("point lies outside the piecewise source boundary")
        return patch.transform.map_point(local)

    def inverse_map(self, point: QPointF) -> QPointF | None:
        """Map one target point into its deterministic source patch."""
        try:
            target = finite_point(point, name="piecewise target")
        except ValueError:
            return None
        patch = next(
            (
                candidate
                for candidate in self.patches
                if candidate.contains_target(target)
            ),
            None,
        )
        return None if patch is None else patch.transform.inverse_map(target)

    def inverted(self) -> PiecewiseLayerTransform:
        """Return the exact inverse finite piecewise mapping."""
        return self._from_patches(
            self.target_boundary,
            self.source_boundary,
            tuple(
                TriangularLayerMappingPatch(patch.target, patch.source)
                for patch in self.patches
            ),
        )

    def followed_by(
        self,
        next_transform: LayerTransform | ProjectiveLayerTransform,
    ) -> PiecewiseLayerTransform:
        """Apply one global affine or projective transform after every patch."""
        if not isinstance(next_transform, (LayerTransform, ProjectiveLayerTransform)):
            raise TypeError("next_transform must be a global layer transform")
        transformed_boundary = tuple(
            next_transform.map_point(point) for point in self.target_boundary
        )
        return self._from_patches(
            self.source_boundary,
            transformed_boundary,
            tuple(
                TriangularLayerMappingPatch(
                    patch.source,
                    _mapped_triangle(patch.target, next_transform),
                )
                for patch in self.patches
            ),
        )

    def preceded_by(
        self,
        previous_transform: LayerTransform | ProjectiveLayerTransform,
    ) -> PiecewiseLayerTransform:
        """Apply one global mapping before entering this finite source boundary."""
        if not isinstance(
            previous_transform,
            (LayerTransform, ProjectiveLayerTransform),
        ):
            raise TypeError("previous_transform must be a global layer transform")
        inverse = previous_transform.inverted()
        if inverse is None:
            raise ValueError("previous layer transform must be invertible")
        transformed_boundary = tuple(
            inverse.map_point(point) for point in self.source_boundary
        )
        return self._from_patches(
            transformed_boundary,
            self.target_boundary,
            tuple(
                TriangularLayerMappingPatch(
                    _mapped_triangle(patch.source, inverse),
                    patch.target,
                )
                for patch in self.patches
            ),
        )

    def map_rect(self, rect: QRect | QRectF) -> QRectF:
        """Return exact conservative target bounds inside the finite cage."""
        return _mapped_clipped_rect(QRectF(rect), self.patches, inverse=False)

    def inverse_map_rect(self, rect: QRect | QRectF) -> QRectF:
        """Return exact conservative source bounds inside the finite target."""
        return _mapped_clipped_rect(QRectF(rect), self.patches, inverse=True)

    def inverse_map_path(self, path: QPainterPath) -> QPainterPath:
        """Map a target path into source space through clipped patches."""
        return _mapped_clipped_path(path, self.patches, inverse=True)

    def map_path(self, path: QPainterPath) -> QPainterPath:
        """Map a source path into target space through clipped patches."""
        return _mapped_clipped_path(path, self.patches, inverse=False)

    def map_bounds(self, bounds: RasterBounds) -> LayerPlacement:
        """Return conservative scene placement of the mapped source boundary."""
        if not isinstance(bounds, RasterBounds):
            raise TypeError("bounds must be RasterBounds")
        rectangle = bounding_rect(self.target_boundary)
        return LayerPlacement(
            rectangle.x(),
            rectangle.y(),
            rectangle.width(),
            rectangle.height(),
        )


def _mapped_clipped_rect(
    rect: QRectF,
    patches: tuple[TriangularLayerMappingPatch, ...],
    *,
    inverse: bool,
) -> QRectF:
    """Map one rectangular path through every intersecting triangle patch."""
    source = QPainterPath()
    source.addRect(rect.normalized())
    return _mapped_clipped_path(source, patches, inverse=inverse).boundingRect()


def _mapped_clipped_path(
    source: QPainterPath,
    patches: tuple[TriangularLayerMappingPatch, ...],
    *,
    inverse: bool,
) -> QPainterPath:
    """Map one path through every intersecting triangle patch."""
    mapped = QPainterPath()
    for patch in patches:
        boundary = patch.target if inverse else patch.source
        clip = QPainterPath()
        clip.addPolygon(QPolygonF(boundary))
        clip.closeSubpath()
        contribution = source.intersected(clip)
        if contribution.isEmpty():
            continue
        transform = patch.transform.inverted() if inverse else patch.transform
        if transform is not None:
            mapped = mapped.united(transform.to_qtransform().map(contribution))
    return mapped


def _mapped_triangle(
    points: tuple[QPointF, QPointF, QPointF],
    transform: LayerTransform | ProjectiveLayerTransform,
) -> tuple[QPointF, QPointF, QPointF]:
    """Map exactly three patch vertices through one global transform."""
    return (
        transform.map_point(points[0]),
        transform.map_point(points[1]),
        transform.map_point(points[2]),
    )


__all__ = ["PiecewiseLayerTransform", "TriangularLayerMappingPatch"]
