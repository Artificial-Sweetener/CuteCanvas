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
"""Worker-side construction of detached canvas resampling products."""

from __future__ import annotations

import uuid
from dataclasses import replace
from math import ceil, floor

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QImage
from qpane.sdk.execution import CancellationToken
from qpane.sdk.raster import AffineImageResampler
from qpane.sdk.scene import LayerTransform, RasterBounds

from ..coverage import (
    AffineCoverageResampler,
    CoverageAssetSnapshot,
    CoverageSnapshot,
    CoverageSurface,
)
from ..coverage.document import CoverageDocument
from ..placed.model import PlacedAssetSnapshot
from ..raster.color_surface import ColorRasterSurface
from ..raster.sparse_grid import SparseRasterSnapshot
from .canvas_geometry import scaled_raster_bounds
from .canvas_resampling import (
    CanvasResamplePlan,
    CanvasResampleProduct,
    CanvasResampleResourceInput,
    CanvasResampleResourceProduct,
    CanvasResamplingMode,
)


def build_resample_product(
    plan: CanvasResamplePlan,
    cancellation: CancellationToken | None = None,
) -> CanvasResampleProduct:
    """Compute every raster product without consulting live document state."""
    products = []
    for item in plan.resources:
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        products.append(_resample_resource(item, plan.local_scale, plan.mode))
    if cancellation is not None:
        cancellation.raise_if_cancelled()
    selection_document = _scaled_coverage_document(
        plan.before.selection_document,
        plan.scene_scale,
        document_id=None,
    )
    selection_coverage = _resample_selection(
        plan.before.selection_coverage,
        plan.scene_scale,
        plan.mode,
    )
    return CanvasResampleProduct(
        plan,
        tuple(products),
        selection_document,
        selection_coverage,
    )


def _resample_resource(
    item: CanvasResampleResourceInput,
    scale: LayerTransform,
    mode: CanvasResamplingMode,
) -> CanvasResampleResourceProduct:
    """Return one source-specific detached resampling product."""
    if isinstance(item.payload, SparseRasterSnapshot):
        surface = ColorRasterSurface.from_sparse_snapshot(item.payload)
        bounds = scaled_raster_bounds(item.payload.bounds, scale)
        image = _project_image(
            surface.snapshot_qimage(),
            item.payload.bounds,
            bounds,
            scale,
            mode,
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        payload = ColorRasterSurface(
            image,
            bounds=bounds,
            extent_policy=item.payload.extent_policy,
        ).sparse_snapshot()
    elif isinstance(item.payload, PlacedAssetSnapshot):
        assert item.payload.image is not None
        target = QSize(
            max(1, round(item.payload.source_size.width() * scale.m11)),
            max(1, round(item.payload.source_size.height() * scale.m22)),
        )
        payload = item.payload.image.scaled(
            target,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            _qt_mode(mode),
        )
    else:
        payload = _resample_coverage(item.payload, item.target_id, scale, mode)
    return CanvasResampleResourceProduct(
        item.source_id,
        item.target_id,
        item.kind,
        payload,
    )


def _resample_coverage(
    snapshot: CoverageAssetSnapshot,
    target_id: uuid.UUID,
    scale: LayerTransform,
    mode: CanvasResamplingMode,
) -> CoverageAssetSnapshot:
    """Scale raster coverage once while retaining semantic mask authorship."""
    surface = CoverageSurface.from_sparse_snapshot(snapshot.raster)
    source = surface.snapshot()
    if source.bounds is None:
        raster = CoverageSurface(
            extent_policy=source.extent_policy,
        ).sparse_snapshot()
    else:
        target_bounds = scaled_raster_bounds(source.bounds, scale)
        projected = AffineCoverageResampler().project(
            source,
            scale,
            target_bounds,
            extent_policy=source.extent_policy,
            smooth=mode is CanvasResamplingMode.SMOOTH,
        )
        raster = CoverageSurface(
            projected.pixels,
            bounds=projected.bounds,
            extent_policy=projected.extent_policy,
        ).sparse_snapshot()
    return CoverageAssetSnapshot(
        raster,
        _scaled_coverage_document(snapshot.retained, scale, document_id=target_id),
        (
            None
            if snapshot.authored_bounds is None
            else scaled_raster_bounds(snapshot.authored_bounds, scale)
        ),
    )


def _resample_selection(
    snapshot: CoverageSnapshot | None,
    scale: LayerTransform,
    mode: CanvasResamplingMode,
) -> CoverageSnapshot | None:
    """Scale evaluated selection coverage for immediate presentation."""
    if snapshot is None or snapshot.bounds is None:
        return snapshot
    destination = _mapped_bounds(snapshot.bounds, scale)
    return AffineCoverageResampler().project(
        snapshot,
        scale,
        destination,
        extent_policy=snapshot.extent_policy,
        smooth=mode is CanvasResamplingMode.SMOOTH,
    )


def _mapped_bounds(bounds: RasterBounds, transform: LayerTransform) -> RasterBounds:
    """Return a tight integer envelope for an axis-aligned scene mapping."""
    rectangle = transform.map_rect(QRectF(bounds.to_qrect()))
    left = floor(rectangle.left())
    top = floor(rectangle.top())
    right = ceil(rectangle.right())
    bottom = ceil(rectangle.bottom())
    return RasterBounds(left, top, max(1, right - left), max(1, bottom - top))


def _scaled_coverage_document(
    document: CoverageDocument | None,
    scale: LayerTransform,
    *,
    document_id: uuid.UUID | None,
) -> CoverageDocument | None:
    """Scale retained coverage transforms without flattening their values."""
    if document is None:
        return None
    return replace(
        document,
        document_id=document.document_id if document_id is None else document_id,
        items=tuple(
            replace(item, transform=item.transform.followed_by(scale))
            for item in document.items
        ),
        revision=document.revision + 1,
        evaluation_token=uuid.uuid4(),
    )


def _project_image(
    image: QImage,
    source_bounds: RasterBounds,
    target_bounds: RasterBounds,
    scale: LayerTransform,
    mode: CanvasResamplingMode,
    image_format: QImage.Format,
) -> QImage:
    """Project pixels through the supported affine Qt primitive."""
    return AffineImageResampler().project(
        image,
        source_bounds=source_bounds,
        transform=scale,
        destination_bounds=target_bounds,
        image_format=image_format,
        smooth=mode is CanvasResamplingMode.SMOOTH,
    )


def _qt_mode(mode: CanvasResamplingMode) -> Qt.TransformationMode:
    """Map the public quality policy onto Qt's supported transformation modes."""
    return (
        Qt.TransformationMode.SmoothTransformation
        if mode is CanvasResamplingMode.SMOOTH
        else Qt.TransformationMode.FastTransformation
    )


__all__ = ["build_resample_product"]
