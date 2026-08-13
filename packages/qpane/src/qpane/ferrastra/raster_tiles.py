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

"""Adapt immutable raster revisions to exact Ferrastra render tiles."""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable, Hashable
from threading import Lock
from typing import Protocol, runtime_checkable

from ferrastra import CancellationToken as NativeCancellationToken
from ferrastra import Engine, EvaluationBudget, Graph, RasterResult, Region
from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage

from ..rendering.render_sampling_grid import AffineSamplingGrid, AxisAlignedSamplingGrid
from ..rendering.render_tile_geometry import RenderTileRequest
from ..rendering.render_tile_types import RenderTileProduct
from ..scene.identity import SourceRenderAssetKey
from ..scene.raster import RasterBounds
from ..scene.raster_sampling import RasterExactSampling
from .qimage import qimage_from_rgba8, qimage_to_rgba8
from .raster_tile_graphs import affine_graph, sampled_view_graph


@runtime_checkable
class _SubscribableCancellation(Protocol):
    """Notify one native request when cooperative cancellation begins."""

    def subscribe(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register a callback and return its bounded unsubscription."""
        ...


class FerrastraRasterTileSource:
    """Evaluate one immutable authoritative QImage revision on requested grids."""

    def __init__(self, image: QImage, asset_key: SourceRenderAssetKey) -> None:
        """Retain detached identity and implicitly shared authoritative pixels."""
        if image.isNull():
            raise ValueError("image must not be null")
        self._image = QImage(image)
        self._asset_key = asset_key
        self._engine: Engine | None = None
        self._source_revision: str | None = None
        self._initialization_lock = Lock()

    @property
    def source_kind(self) -> str:
        """Return the exact raster cache namespace."""
        return f"{self._asset_key.source_kind}-exact-raster"

    @property
    def source_id(self) -> uuid.UUID:
        """Return the source identity shared with its presentation products."""
        return self._asset_key.source_id

    @property
    def revision_key(self) -> Hashable:
        """Return the immutable authoritative pixel revision."""
        return self._asset_key.source_revision

    @property
    def fallback_key(self) -> Hashable:
        """Return geometry compatibility for retained prior revisions."""
        return self._image.width(), self._image.height()

    @property
    def bounds(self) -> RasterBounds:
        """Return zero-origin authoritative raster bounds."""
        return RasterBounds(0, 0, self._image.width(), self._image.height())

    def render_tiles(
        self,
        requests: tuple[RenderTileRequest, ...],
        is_cancelled: Callable[[], bool],
    ) -> tuple[RenderTileProduct, ...]:
        """Evaluate one complete tile batch with cancellation and exact geometry."""
        if not requests or is_cancelled():
            return ()
        engine, source_revision = self._native_source(is_cancelled)
        products: list[RenderTileProduct] = []
        for request in requests:
            if is_cancelled():
                return ()
            product = self._render_tile(
                engine,
                source_revision,
                request,
                is_cancelled,
            )
            if product is None:
                return ()
            products.append(product)
        return tuple(products)

    def _native_source(
        self,
        is_cancelled: Callable[[], bool],
    ) -> tuple[Engine, str]:
        """Create the retained native source lazily away from the GUI thread."""
        with self._initialization_lock:
            if self._engine is None or self._source_revision is None:
                if is_cancelled():
                    raise RuntimeError("render refinement cancelled")
                source = qimage_to_rgba8(self._image)
                engine = Engine()
                revision = engine.add_rgba8(
                    source.pixels,
                    source.width,
                    source.height,
                    stride_bytes=source.stride_bytes,
                )
                self._engine = engine
                self._source_revision = revision
            engine = self._engine
            revision = self._source_revision
            if engine is None or revision is None:
                raise RuntimeError("native raster source initialization failed")
            return engine, revision

    def _render_tile(
        self,
        engine: Engine,
        source_revision: str,
        request: RenderTileRequest,
        is_cancelled: Callable[[], bool],
    ) -> RenderTileProduct | None:
        """Evaluate and adapt one tile without publishing partial native output."""
        grid = request.key.sampling_grid
        if isinstance(grid, AffineSamplingGrid):
            return self._render_affine_tile(
                engine,
                source_revision,
                request,
                grid,
                is_cancelled,
            )
        scale_x, scale_y = _sample_scales(request, grid)
        width = max(1, round(request.paint_rect.width() * scale_x))
        height = max(1, round(request.paint_rect.height() * scale_y))
        graph = sampled_view_graph(
            source_revision,
            (self._image.width(), self._image.height()),
            (width, height),
            source_center=(
                request.paint_rect.x() + 0.5 / scale_x - 0.5,
                request.paint_rect.y() + 0.5 / scale_y - 0.5,
            ),
            source_step=(1.0 / scale_x, 1.0 / scale_y),
            sampling=_exact_sampling(request),
            reconstruction_space=request.key.reconstruction_space,
        )
        compiled = engine.compile(graph)
        region = Region(0, 0, width, height)
        requirements = engine.requirements(compiled, "result", region)
        native_cancellation = NativeCancellationToken()
        unsubscribe = (
            is_cancelled.subscribe(native_cancellation.cancel)
            if isinstance(is_cancelled, _SubscribableCancellation)
            else lambda: None
        )
        try:
            if is_cancelled():
                return None
            result = engine.evaluate(
                compiled,
                "result",
                region,
                EvaluationBudget(
                    memory_bytes=requirements.memory_bytes,
                    scratch_bytes=requirements.scratch_bytes,
                    cancellation=native_cancellation,
                ),
            )
        except Exception:
            if is_cancelled():
                return None
            raise
        finally:
            unsubscribe()
        core = request.source_rect
        image_source_rect = QRectF(
            (core.x() - request.paint_rect.x()) * scale_x,
            (core.y() - request.paint_rect.y()) * scale_y,
            core.width() * scale_x,
            core.height() * scale_y,
        )
        source_bounds = QRectF(
            0.0,
            0.0,
            float(self._image.width()),
            float(self._image.height()),
        )
        return RenderTileProduct(
            request.key,
            core,
            qimage_from_rgba8(
                result.pixels,
                result.width,
                result.height,
                result.stride_bytes,
            ),
            image_source_rect,
            core.intersected(source_bounds),
        )

    def _render_affine_tile(
        self,
        engine: Engine,
        source_revision: str,
        request: RenderTileRequest,
        grid: AffineSamplingGrid,
        is_cancelled: Callable[[], bool],
    ) -> RenderTileProduct | None:
        """Evaluate one affine projection tile directly on the physical panel grid."""
        width = max(1, round(request.paint_rect.width() * grid.device_pixel_ratio))
        height = max(1, round(request.paint_rect.height() * grid.device_pixel_ratio))
        center_x = request.paint_rect.x() + 0.5 / grid.device_pixel_ratio
        center_y = request.paint_rect.y() + 0.5 / grid.device_pixel_ratio
        graph = affine_graph(
            source_revision,
            (self._image.width(), self._image.height()),
            (width, height),
            matrix=(
                grid.source_m11 / grid.device_pixel_ratio,
                grid.source_m12 / grid.device_pixel_ratio,
                grid.source_m21 / grid.device_pixel_ratio,
                grid.source_m22 / grid.device_pixel_ratio,
                grid.source_m11 * center_x
                + grid.source_m21 * center_y
                + grid.source_tx
                - 0.5,
                grid.source_m12 * center_x
                + grid.source_m22 * center_y
                + grid.source_ty
                - 0.5,
            ),
            sampling=_exact_sampling(request),
            reconstruction_space=request.key.reconstruction_space,
        )
        result = self._evaluate(engine, graph, width, height, is_cancelled)
        if result is None:
            return None
        image = qimage_from_rgba8(
            result.pixels,
            result.width,
            result.height,
            result.stride_bytes,
        )
        image.setDevicePixelRatio(grid.device_pixel_ratio)
        bleed_x = (
            request.source_rect.x() - request.paint_rect.x()
        ) * grid.device_pixel_ratio
        bleed_y = (
            request.source_rect.y() - request.paint_rect.y()
        ) * grid.device_pixel_ratio
        return RenderTileProduct(
            request.key,
            request.source_rect,
            image,
            QRectF(
                bleed_x,
                bleed_y,
                request.source_rect.width() * grid.device_pixel_ratio,
                request.source_rect.height() * grid.device_pixel_ratio,
            ),
            request.source_rect,
        )

    @staticmethod
    def _evaluate(
        engine: Engine,
        graph: Graph,
        width: int,
        height: int,
        is_cancelled: Callable[[], bool],
    ) -> RasterResult | None:
        """Evaluate one graph with subscribed cancellation and exact admission."""
        compiled = engine.compile(graph)
        region = Region(0, 0, width, height)
        requirements = engine.requirements(compiled, "result", region)
        native_cancellation = NativeCancellationToken()
        unsubscribe = (
            is_cancelled.subscribe(native_cancellation.cancel)
            if isinstance(is_cancelled, _SubscribableCancellation)
            else lambda: None
        )
        try:
            if is_cancelled():
                return None
            return engine.evaluate(
                compiled,
                "result",
                region,
                EvaluationBudget(
                    memory_bytes=requirements.memory_bytes,
                    scratch_bytes=requirements.scratch_bytes,
                    cancellation=native_cancellation,
                ),
            )
        except Exception:
            if is_cancelled():
                return None
            raise
        finally:
            unsubscribe()


def _sample_scales(
    request: RenderTileRequest,
    grid: AxisAlignedSamplingGrid | None,
) -> tuple[float, float]:
    """Return explicit exact density or the legacy uniform request density."""
    if grid is not None:
        return grid.scale_x, grid.scale_y
    if not math.isfinite(request.key.scale) or request.key.scale <= 0.0:
        raise ValueError("render tile scale must be finite and positive")
    return request.key.scale, request.key.scale


def _exact_sampling(request: RenderTileRequest) -> RasterExactSampling:
    """Return the required exact sampling identity for one native request."""
    sampling = request.key.exact_sampling
    if sampling is None:
        raise ValueError("Ferrastra raster tiles require an exact sampling identity")
    return sampling


__all__ = ["FerrastraRasterTileSource"]
