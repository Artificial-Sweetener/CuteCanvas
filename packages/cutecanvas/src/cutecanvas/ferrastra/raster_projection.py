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

"""Project authoring rasters through canonical affine evaluation graphs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from PySide6.QtCore import QSize
from PySide6.QtGui import QImage

from ferrastra import CancellationToken as NativeCancellationToken
from ferrastra import Engine, EvaluationBudget, Graph, RasterResult, Region
from qpane.sdk.scene import LayerTransform, RasterBounds

from .affine_projection_graph import build_affine_projection_graph
from .qimage import qimage_from_rgba8, qimage_to_rgba8
from .scale_graph import build_lanczos3_scale_graph


class _Cancellation(Protocol):
    """Expose cancellation state and bounded native notification."""

    @property
    def is_cancelled(self) -> bool:
        """Return whether cancellation has begun."""
        ...

    def subscribe(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register one callback and return its unsubscription."""
        ...


class NativeRasterProjector:
    """Evaluate exact RGBA8 affine products for CuteCanvas authoring workflows."""

    def scale(
        self,
        image: QImage,
        target_size: QSize,
        *,
        linear: bool = True,
        cancellation: _Cancellation | None = None,
    ) -> QImage:
        """Return one exact zero-origin raster at the requested dimensions."""
        if image.isNull() or target_size.isEmpty():
            raise ValueError("source and target dimensions must be positive")
        if linear:
            return self._scale_lanczos3(image, target_size, cancellation)
        return self.project(
            image,
            source_bounds=RasterBounds(0, 0, image.width(), image.height()),
            transform=LayerTransform(
                m11=target_size.width() / image.width(),
                m22=target_size.height() / image.height(),
            ),
            destination_bounds=RasterBounds(
                0,
                0,
                target_size.width(),
                target_size.height(),
            ),
            linear=False,
            cancellation=cancellation,
        )

    @staticmethod
    def _scale_lanczos3(
        image: QImage,
        target_size: QSize,
        cancellation: _Cancellation | None,
    ) -> QImage:
        """Evaluate one whole-source reconstruction product."""
        source = qimage_to_rgba8(image)
        engine = Engine()
        revision = engine.add_rgba8(
            source.pixels,
            source.width,
            source.height,
            stride_bytes=source.stride_bytes,
        )
        graph = build_lanczos3_scale_graph(
            revision,
            (source.width, source.height),
            (target_size.width(), target_size.height()),
        )
        result = _evaluate(
            engine,
            graph,
            target_size.width(),
            target_size.height(),
            cancellation,
        )
        return qimage_from_rgba8(
            result.pixels,
            result.width,
            result.height,
            result.stride_bytes,
            image.format(),
        )

    def project(
        self,
        image: QImage,
        *,
        source_bounds: RasterBounds,
        transform: LayerTransform,
        destination_bounds: RasterBounds,
        image_format: QImage.Format = QImage.Format_ARGB32_Premultiplied,
        linear: bool = True,
        cancellation: _Cancellation | None = None,
    ) -> QImage:
        """Return one bounded destination-coordinate affine raster product."""
        target = QImage(
            destination_bounds.width, destination_bounds.height, image_format
        )
        target.fill(0)
        if (
            image.isNull()
            or not transform.is_invertible
            or (cancellation is not None and cancellation.is_cancelled)
        ):
            return target
        source = qimage_to_rgba8(image)
        engine = Engine()
        revision = engine.add_rgba8(
            source.pixels,
            source.width,
            source.height,
            stride_bytes=source.stride_bytes,
        )
        graph = build_affine_projection_graph(
            revision,
            (source.width, source.height),
            transform,
            source_bounds,
            destination_bounds,
            source_operation="ferrastra.source.raster",
            projection_operation=(
                "ferrastra.resample.affine-bilinear"
                if linear
                else "ferrastra.resample.affine-nearest"
            ),
            working_space="srgb_linear" if linear else None,
        )
        result = _evaluate(
            engine,
            graph,
            destination_bounds.width,
            destination_bounds.height,
            cancellation,
        )
        return qimage_from_rgba8(
            result.pixels,
            result.width,
            result.height,
            result.stride_bytes,
            image_format,
        )


def _evaluate(
    engine: Engine,
    graph: Graph,
    width: int,
    height: int,
    cancellation: _Cancellation | None,
) -> RasterResult:
    """Evaluate one exact raster graph with optional native cancellation."""
    compiled = engine.compile(graph)
    region = Region(0, 0, width, height)
    requirements = engine.requirements(compiled, "result", region)
    native_cancellation = NativeCancellationToken()
    unsubscribe = (
        cancellation.subscribe(native_cancellation.cancel)
        if cancellation is not None
        else lambda: None
    )
    try:
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
        if not isinstance(result, RasterResult):
            raise TypeError("raster graph published a non-raster product")
        return result
    finally:
        unsubscribe()


__all__ = ["NativeRasterProjector"]
