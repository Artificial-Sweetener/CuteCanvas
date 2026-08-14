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

"""Public hybrid-coverage authoring controls."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from math import isfinite

from PySide6.QtCore import QPointF, QRect, QRectF
from PySide6.QtGui import QImage

from qpane.sdk.raster import qimage_to_numpy_grayscale8
from qpane.sdk.scene import RasterBounds
from qpane.sdk.vector import VectorShapeKind

from ..coverage import (
    CoverageCombineMode,
    CoverageGeometryFactory,
    CoverageShapeOptions,
    CoverageSnapshot,
    RasterCoverageItem,
    VectorCoverageItem,
)
from ..types import CoverageCoordinateSpace, PixelSelectionMode, RasterExtentPolicy


class CoverageApiMixin:
    """Expose retained-shape options and explicit mask flattening."""

    def addCoverageShape(
        self,
        shape: VectorShapeKind,
        bounds: QRectF,
        mode: PixelSelectionMode = PixelSelectionMode.ADD,
        *,
        feather_radius: float | None = None,
        coordinate_space: CoverageCoordinateSpace = CoverageCoordinateSpace.TARGET,
    ) -> uuid.UUID | None:
        """Add one retained rectangle or ellipse to the active coverage target.

        Layer targets interpret ``bounds`` in layer-local coordinates. The pixel
        selection target interprets them in scene coordinates.

        Args:
            shape: Rectangle or ellipse geometry to retain.
            bounds: Positive target-coordinate bounds for the shape.
            mode: Coverage algebra used to combine the new item.
            feather_radius: Optional edge feather in target pixels. ``None`` uses
                the configured coverage-shape option.
            coordinate_space: Whether bounds use target units or normalized
                fractions of the active target's finite bounds.

        Returns:
            Stable authored-item ID, or None when the active target does not
            accept retained coverage or the commit was rejected.
        """
        if not isinstance(shape, VectorShapeKind):
            raise TypeError("shape must be a VectorShapeKind")
        rectangle = self._coverage_bounds(bounds, coordinate_space)
        combine = _coverage_mode(mode)
        radius = self._coverage_feather_radius(feather_radius)
        geometry = CoverageGeometryFactory()
        vector = (
            geometry.rectangle(rectangle)
            if shape is VectorShapeKind.RECTANGLE
            else geometry.ellipse(rectangle)
        )
        item_id = uuid.uuid4()
        item = VectorCoverageItem(
            item_id,
            vector,
            combine,
            feather_radius=radius,
        )
        return (
            item_id if self.paintingCoordinator().commit_coverage_item(item) else None
        )

    def addCoveragePolygon(
        self,
        points: Iterable[QPointF],
        mode: PixelSelectionMode = PixelSelectionMode.ADD,
        *,
        feather_radius: float | None = None,
        coordinate_space: CoverageCoordinateSpace = CoverageCoordinateSpace.TARGET,
    ) -> uuid.UUID | None:
        """Add one retained closed polygon to the active coverage target.

        Args:
            points: Three or more target-coordinate polygon vertices.
            mode: Coverage algebra used to combine the new item.
            feather_radius: Optional edge feather in target pixels. ``None`` uses
                the configured coverage-shape option.
            coordinate_space: Whether vertices use target units or normalized
                fractions of the active target's finite bounds.

        Returns:
            Stable authored-item ID, or None when the commit was rejected.
        """
        vertices = tuple(QPointF(point) for point in points)
        if len(vertices) < 3:
            raise ValueError("points must contain at least three vertices")
        if not all(
            isfinite(value) for point in vertices for value in (point.x(), point.y())
        ):
            raise ValueError("points must contain finite coordinates")
        vertices = self._coverage_points(vertices, coordinate_space)
        item_id = uuid.uuid4()
        item = VectorCoverageItem(
            item_id,
            CoverageGeometryFactory().lasso(vertices),
            _coverage_mode(mode),
            feather_radius=self._coverage_feather_radius(feather_radius),
        )
        return (
            item_id if self.paintingCoordinator().commit_coverage_item(item) else None
        )

    def addCoverageImage(
        self,
        coverage: QImage,
        bounds: QRect,
        mode: PixelSelectionMode = PixelSelectionMode.ADD,
    ) -> uuid.UUID | None:
        """Add arbitrary 8-bit coverage to the active coverage target.

        Args:
            coverage: Grayscale or color image interpreted as soft coverage.
            bounds: Target-coordinate bounds occupied by ``coverage``.
            mode: Coverage algebra used to combine the new item.

        Returns:
            Stable authored-item ID, or None when the commit was rejected.
        """
        if not isinstance(coverage, QImage):
            raise TypeError("coverage must be a QImage")
        if not isinstance(bounds, QRect):
            raise TypeError("bounds must be a QRect")
        if coverage.isNull():
            raise ValueError("coverage must not be null")
        if coverage.size() != bounds.size() or bounds.isEmpty():
            raise ValueError("coverage dimensions must match positive bounds")
        item_id = uuid.uuid4()
        item = RasterCoverageItem(
            item_id,
            CoverageSnapshot(
                bounds=RasterBounds.from_qrect(bounds),
                extent_policy=RasterExtentPolicy.EXPAND_ON_WRITE,
                pixels=qimage_to_numpy_grayscale8(coverage),
            ),
            _coverage_mode(mode),
        )
        return (
            item_id if self.paintingCoordinator().commit_coverage_item(item) else None
        )

    def coverageShapeOptions(self) -> CoverageShapeOptions:
        """Return options applied to future mask and selection shapes."""
        return self.coverageShapeConfiguration().options

    def configureCoverageShapes(self, *, feather_radius: float | None = None) -> bool:
        """Configure future retained coverage shape commits."""
        return self.coverageShapeConfiguration().configure(
            feather_radius=feather_radius
        )

    def rasterizeMaskCoverage(self, mask_id: uuid.UUID) -> bool:
        """Flatten retained mask authorship into sparse raster coverage reversibly."""
        service = getattr(self, "mask_service", None)
        if service is None:
            return False
        return service.controller.edits.rasterize_coverage(mask_id)

    def _coverage_feather_radius(self, value: float | None) -> float:
        """Return one validated explicit or configured feather radius."""
        radius = (
            self.coverageShapeConfiguration().options.feather_radius
            if value is None
            else float(value)
        )
        if not isfinite(radius) or radius < 0.0:
            raise ValueError("feather_radius must be finite and non-negative")
        return radius

    def _coverage_bounds(
        self,
        bounds: QRectF,
        coordinate_space: CoverageCoordinateSpace,
    ) -> QRectF:
        """Resolve public shape bounds into active-target coordinates."""
        rectangle = _validated_shape_bounds(bounds)
        if not isinstance(coordinate_space, CoverageCoordinateSpace):
            raise TypeError("coordinate_space must be a CoverageCoordinateSpace")
        if coordinate_space is CoverageCoordinateSpace.TARGET:
            return rectangle
        target = self._active_coverage_bounds()
        if target is None or target.isEmpty():
            raise RuntimeError("the active coverage target has no finite bounds")
        return QRectF(
            target.x() + rectangle.x() * target.width(),
            target.y() + rectangle.y() * target.height(),
            rectangle.width() * target.width(),
            rectangle.height() * target.height(),
        )

    def _coverage_points(
        self,
        points: tuple[QPointF, ...],
        coordinate_space: CoverageCoordinateSpace,
    ) -> tuple[QPointF, ...]:
        """Resolve public polygon vertices into active-target coordinates."""
        if not isinstance(coordinate_space, CoverageCoordinateSpace):
            raise TypeError("coordinate_space must be a CoverageCoordinateSpace")
        if coordinate_space is CoverageCoordinateSpace.TARGET:
            return points
        target = self._active_coverage_bounds()
        if target is None or target.isEmpty():
            raise RuntimeError("the active coverage target has no finite bounds")
        return tuple(
            QPointF(
                target.x() + point.x() * target.width(),
                target.y() + point.y() * target.height(),
            )
            for point in points
        )

    def _active_coverage_bounds(self) -> QRectF | None:
        """Return finite bounds for normalized active-target authoring."""
        target = self.paintTargetState()
        scene = self.currentScene()
        if target is None or scene is None:
            return None
        if target.layer_id is None:
            return QRectF(scene.bounds)
        raster = self.rasterSurfaceState(target.scene_id, target.layer_id)
        if raster is not None:
            return QRectF(raster.bounds)
        return self.layerLocalBounds(target.scene_id, target.layer_id)


def _coverage_mode(mode: PixelSelectionMode) -> CoverageCombineMode:
    """Convert one public selection algebra value to shared coverage algebra."""
    if not isinstance(mode, PixelSelectionMode):
        raise TypeError("mode must be a PixelSelectionMode")
    return CoverageCombineMode(mode.value)


def _validated_shape_bounds(bounds: QRectF) -> QRectF:
    """Return detached normalized positive finite shape bounds."""
    if not isinstance(bounds, QRectF):
        raise TypeError("bounds must be a QRectF")
    rectangle = QRectF(bounds).normalized()
    if rectangle.isEmpty() or not all(
        isfinite(value)
        for value in (
            rectangle.x(),
            rectangle.y(),
            rectangle.width(),
            rectangle.height(),
        )
    ):
        raise ValueError("bounds must be finite with positive dimensions")
    return rectangle
