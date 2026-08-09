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

"""Render-frame mappings from one layer source into panel coordinates."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import pairwise
from typing import TypeAlias, overload

from PySide6.QtCore import QPointF, QRect, QRectF
from PySide6.QtGui import QPainterPath, QPolygonF, QTransform

from ..scene.bilinear import BilinearLayerTransform
from ..scene.piecewise import PiecewiseLayerTransform

_BILINEAR_STRIPS = 24
_APEX_SUBPIXEL_DISTANCE = 0.25


@dataclass(frozen=True, slots=True)
class PanelMappingPatch:
    """Carry one source polygon and its projective panel transform."""

    source: tuple[QPointF, ...]
    panel: tuple[QPointF, ...]
    transform: QTransform

    def __post_init__(self) -> None:
        """Detach mutable Qt values from the frame-owned mapping."""
        source = tuple(QPointF(point) for point in self.source)
        panel = tuple(QPointF(point) for point in self.panel)
        if len(source) not in (3, 4) or len(panel) != len(source):
            raise ValueError(
                "panel patches require matching triangles or quadrilaterals"
            )
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "panel", panel)
        object.__setattr__(self, "transform", QTransform(self.transform))

    @property
    def source_path(self) -> QPainterPath:
        """Return the closed source polygon used to clip this patch."""
        return _polygon_path(self.source)

    @property
    def panel_path(self) -> QPainterPath:
        """Return the closed panel polygon covered by this patch."""
        return _polygon_path(self.panel)


@dataclass(frozen=True, slots=True)
class PiecewisePanelMapping:
    """Map one finite source cage into a panel through affine patches."""

    patches: tuple[PanelMappingPatch, ...]
    outer_panel_boundary: tuple[QPointF, ...] | None = None
    _panel_path: QPainterPath = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Require a nonempty immutable patch set."""
        patches = tuple(self.patches)
        if not patches:
            raise ValueError("piecewise panel mapping requires at least one patch")
        object.__setattr__(self, "patches", patches)
        boundary = self.outer_panel_boundary
        object.__setattr__(
            self,
            "outer_panel_boundary",
            None if boundary is None else tuple(QPointF(point) for point in boundary),
        )
        object.__setattr__(
            self,
            "_panel_path",
            (
                _united_panel_path(patches)
                if boundary is None
                else _polygon_path(tuple(QPointF(point) for point in boundary))
            ),
        )

    @classmethod
    def from_layer_mapping(
        cls,
        mapping: PiecewiseLayerTransform | BilinearLayerTransform,
        target_to_panel: QTransform,
    ) -> PiecewisePanelMapping:
        """Project a bounded layer mapping through one viewport transform."""
        if not isinstance(mapping, (PiecewiseLayerTransform, BilinearLayerTransform)):
            raise TypeError("mapping must be a bounded layer mapping")
        if not isinstance(target_to_panel, QTransform):
            raise TypeError("target_to_panel must be QTransform")
        if isinstance(mapping, BilinearLayerTransform):
            return cls(
                _bilinear_panel_patches(mapping, target_to_panel),
                tuple(target_to_panel.map(point) for point in mapping.target_boundary),
            )
        return cls(
            tuple(
                PanelMappingPatch(
                    source=patch.source,
                    panel=_mapped_triangle(target_to_panel, patch.target),
                    transform=patch.transform.to_qtransform() * target_to_panel,
                )
                for patch in mapping.patches
            )
        )

    @property
    def is_invertible(self) -> bool:
        """Return whether every affine patch can be inverted."""
        return all(patch.transform.isInvertible() for patch in self.patches)

    @property
    def panel_path(self) -> QPainterPath:
        """Return the detached outer coverage of the complete finite mapping."""
        return QPainterPath(self._panel_path)

    def isAffine(self) -> bool:
        """Return False because the complete mapping is not globally affine."""
        return False

    def map_point(self, point: QPointF) -> QPointF:
        """Map one source point through its containing triangle."""
        patch = next(
            (
                candidate
                for candidate in self.patches
                if candidate.source_path.contains(point)
            ),
            None,
        )
        if patch is None:
            patch = _patch_containing_boundary_point(self.patches, point, source=True)
        if patch is None:
            raise ValueError("point lies outside the piecewise panel source")
        return patch.transform.map(point)

    @overload
    def map(self, value: QPointF) -> QPointF:
        """Map one source point into panel coordinates."""

    @overload
    def map(self, value: QPainterPath) -> QPainterPath:
        """Map one source path into panel coordinates."""

    def map(self, value: QPointF | QPainterPath) -> QPointF | QPainterPath:
        """Map a point or clipped path through all applicable patches."""
        if isinstance(value, QPointF):
            return self.map_point(value)
        if isinstance(value, QPainterPath):
            return self.map_path(value)
        raise TypeError("piecewise panel mapping accepts QPointF or QPainterPath")

    def map_path(self, path: QPainterPath) -> QPainterPath:
        """Map a path by clipping it to each source triangle first."""
        mapped = QPainterPath()
        mapped.setFillRule(path.fillRule())
        for patch in self.patches:
            contribution = path.intersected(patch.source_path)
            if not contribution.isEmpty():
                mapped = mapped.united(patch.transform.map(contribution))
        return mapped

    def mapRect(self, rect: QRect | QRectF) -> QRectF:
        """Return conservative panel bounds for one source rectangle."""
        path = QPainterPath()
        path.addRect(QRectF(rect))
        return self.map_path(path).boundingRect()

    def inverted(self) -> tuple[PiecewisePanelMapping, bool]:
        """Return an exact inverse patch mapping and its validity."""
        inverse_patches: list[PanelMappingPatch] = []
        for patch in self.patches:
            inverse, invertible = patch.transform.inverted()
            if not invertible:
                return self, False
            inverse_patches.append(
                PanelMappingPatch(
                    source=patch.panel,
                    panel=patch.source,
                    transform=inverse,
                )
            )
        return PiecewisePanelMapping(tuple(inverse_patches)), True

    def translated(self, delta: QPointF) -> PiecewisePanelMapping:
        """Return the mapping shifted by one panel-space displacement."""
        offset = QPointF(delta)
        boundary = self.outer_panel_boundary
        return PiecewisePanelMapping(
            tuple(
                PanelMappingPatch(
                    source=patch.source,
                    panel=tuple(point + offset for point in patch.panel),
                    transform=_translated_transform(patch.transform, offset),
                )
                for patch in self.patches
            ),
            (None if boundary is None else tuple(point + offset for point in boundary)),
        )


PanelLayerMapping: TypeAlias = QTransform | PiecewisePanelMapping
PanelMappingKey: TypeAlias = tuple[float, ...]


def detached_panel_mapping(mapping: PanelLayerMapping) -> PanelLayerMapping:
    """Detach one mutable Qt transform or retain an immutable piecewise value."""
    if isinstance(mapping, QTransform):
        return QTransform(mapping)
    if isinstance(mapping, PiecewisePanelMapping):
        return mapping
    raise TypeError("mapping must be a panel layer mapping")


def panel_mapping_patches(mapping: PanelLayerMapping) -> tuple[PanelMappingPatch, ...]:
    """Return affine draw patches for either supported panel mapping."""
    if isinstance(mapping, PiecewisePanelMapping):
        return mapping.patches
    raise TypeError("a global transform does not expose finite source patches")


def panel_mapping_key(mapping: PanelLayerMapping) -> PanelMappingKey:
    """Return exact immutable frame identity for one panel mapping."""
    if isinstance(mapping, QTransform):
        return _transform_key(mapping)
    return tuple(
        value
        for patch in mapping.patches
        for value in (
            *(
                coordinate
                for point in patch.source
                for coordinate in (point.x(), point.y())
            ),
            *_transform_key(patch.transform),
        )
    )


def _polygon_path(points: tuple[QPointF, ...]) -> QPainterPath:
    """Return a closed path for one detached polygon."""
    path = QPainterPath()
    path.addPolygon(QPolygonF(points))
    path.closeSubpath()
    return path


def _mapped_triangle(
    transform: QTransform,
    points: tuple[QPointF, QPointF, QPointF],
) -> tuple[QPointF, QPointF, QPointF]:
    """Map exactly three patch vertices through one panel transform."""
    return (
        transform.map(points[0]),
        transform.map(points[1]),
        transform.map(points[2]),
    )


def _united_panel_path(patches: tuple[PanelMappingPatch, ...]) -> QPainterPath:
    """Return one coverage path without internal triangulation boundaries."""
    united = QPainterPath()
    for patch in patches:
        united = united.united(patch.panel_path)
    return united


def _transform_key(transform: QTransform) -> tuple[float, ...]:
    """Return all homogeneous coefficients in Qt storage order."""
    return (
        transform.m11(),
        transform.m12(),
        transform.m13(),
        transform.m21(),
        transform.m22(),
        transform.m23(),
        transform.m31(),
        transform.m32(),
        transform.m33(),
    )


def _translated_transform(transform: QTransform, delta: QPointF) -> QTransform:
    """Translate one detached panel transform without changing its linear part."""
    return QTransform(
        transform.m11(),
        transform.m12(),
        transform.m13(),
        transform.m21(),
        transform.m22(),
        transform.m23(),
        transform.dx() + delta.x(),
        transform.dy() + delta.y(),
        transform.m33(),
    )


def _patch_containing_boundary_point(
    patches: tuple[PanelMappingPatch, ...],
    point: QPointF,
    *,
    source: bool,
) -> PanelMappingPatch | None:
    """Resolve points on a triangle edge despite path boundary semantics."""
    tolerance = 1e-7
    for patch in patches:
        triangle = patch.source if source else patch.panel
        if any(
            _point_on_segment(
                point,
                triangle[index],
                triangle[(index + 1) % len(triangle)],
                tolerance,
            )
            for index in range(len(triangle))
        ):
            return patch
    return None


def _bilinear_panel_patches(
    mapping: BilinearLayerTransform,
    target_to_panel: QTransform,
) -> tuple[PanelMappingPatch, ...]:
    """Approximate one joined-edge mapping with bounded projective strips."""
    apex = target_to_panel.map(mapping.target_boundary[0])
    panel_base = tuple(
        target_to_panel.map(point) for point in mapping.target_boundary[2:4]
    )
    maximum_radius = max(
        math.hypot(point.x() - apex.x(), point.y() - apex.y()) for point in panel_base
    )
    first_v = min(
        1.0 / _BILINEAR_STRIPS,
        _APEX_SUBPIXEL_DISTANCE / max(maximum_radius, 1.0),
    )
    levels = [first_v]
    levels.extend(
        value
        for index in range(1, _BILINEAR_STRIPS + 1)
        for value in (index / _BILINEAR_STRIPS,)
        if value > first_v
    )
    patches: list[PanelMappingPatch] = []
    for start_v, end_v in pairwise(levels):
        source = tuple(
            mapping.point_at(u, v)
            for u, v in (
                (0.0, start_v),
                (1.0, start_v),
                (1.0, end_v),
                (0.0, end_v),
            )
        )
        panel = tuple(
            target_to_panel.map(mapping.point_at(u, v, target=True))
            for u, v in (
                (0.0, start_v),
                (1.0, start_v),
                (1.0, end_v),
                (0.0, end_v),
            )
        )
        patches.append(
            PanelMappingPatch(
                source,
                panel,
                QTransform.quadToQuad(QPolygonF(source), QPolygonF(panel)),
            )
        )
    return tuple(patches)


def _point_on_segment(
    point: QPointF,
    start: QPointF,
    end: QPointF,
    tolerance: float,
) -> bool:
    """Return whether one point lies on a finite segment within tolerance."""
    edge = end - start
    relative = point - start
    cross = edge.x() * relative.y() - edge.y() * relative.x()
    if abs(cross) > tolerance * max(1.0, abs(edge.x()), abs(edge.y())):
        return False
    dot = relative.x() * edge.x() + relative.y() * edge.y()
    length_squared = edge.x() * edge.x() + edge.y() * edge.y()
    return -tolerance <= dot <= length_squared + tolerance


__all__ = [
    "PanelLayerMapping",
    "PanelMappingKey",
    "PanelMappingPatch",
    "PiecewisePanelMapping",
    "detached_panel_mapping",
    "panel_mapping_key",
    "panel_mapping_patches",
]
