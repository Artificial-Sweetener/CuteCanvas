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

"""Project scalar authoring coverage through canonical affine evaluation graphs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

import numpy as np
import numpy.typing as npt
from ferrastra import CancellationToken as NativeCancellationToken
from ferrastra import CoverageResult, Engine, EvaluationBudget, Region
from PySide6.QtCore import QSize
from qpane.sdk.scene import LayerTransform, RasterBounds

from .affine_projection_graph import build_affine_projection_graph


class _Cancellation(Protocol):
    """Expose cancellation state and bounded native notification."""

    @property
    def is_cancelled(self) -> bool:
        """Return whether cancellation has begun."""
        ...

    def subscribe(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register one callback and return its unsubscription."""
        ...


class NativeCoverageProjector:
    """Evaluate exact range-preserving Coverage8 affine products."""

    def scale(
        self,
        pixels: npt.NDArray[np.uint8],
        target_size: QSize,
        *,
        linear: bool = True,
        cancellation: _Cancellation | None = None,
    ) -> npt.NDArray[np.uint8]:
        """Return one exact zero-origin coverage field at requested dimensions."""
        source = _canonical_coverage(pixels)
        if target_size.isEmpty():
            raise ValueError("target dimensions must be positive")
        return self.project(
            source,
            source_bounds=RasterBounds(0, 0, source.shape[1], source.shape[0]),
            transform=LayerTransform(
                m11=target_size.width() / source.shape[1],
                m22=target_size.height() / source.shape[0],
            ),
            destination_bounds=RasterBounds(
                0,
                0,
                target_size.width(),
                target_size.height(),
            ),
            linear=linear,
            filter_mode=(
                "area"
                if linear
                and (
                    target_size.width() < source.shape[1]
                    or target_size.height() < source.shape[0]
                )
                else None
            ),
            edge_mode="clamp",
            cancellation=cancellation,
        )

    def project(
        self,
        pixels: npt.NDArray[np.uint8],
        *,
        source_bounds: RasterBounds,
        transform: LayerTransform,
        destination_bounds: RasterBounds,
        linear: bool = True,
        filter_mode: str | None = None,
        edge_mode: str = "transparent",
        cancellation: _Cancellation | None = None,
    ) -> npt.NDArray[np.uint8]:
        """Return one detached destination-coordinate Coverage8 product."""
        source = _canonical_coverage(pixels)
        if not transform.is_invertible or (
            cancellation is not None and cancellation.is_cancelled
        ):
            return np.zeros(
                (destination_bounds.height, destination_bounds.width),
                dtype=np.uint8,
            )
        engine = Engine()
        revision = engine.add_coverage8(
            memoryview(source).cast("B"),
            source.shape[1],
            source.shape[0],
            stride_bytes=source.strides[0],
        )
        graph = build_affine_projection_graph(
            revision,
            (source.shape[1], source.shape[0]),
            transform,
            source_bounds,
            destination_bounds,
            source_operation="ferrastra.source.coverage",
            projection_operation="ferrastra.resample.coverage-affine",
            filter_mode=filter_mode or ("linear" if linear else "nearest"),
            edge_mode=edge_mode,
        )
        compiled = engine.compile(graph)
        region = Region(0, 0, destination_bounds.width, destination_bounds.height)
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
        finally:
            unsubscribe()
        if not isinstance(result, CoverageResult):
            raise TypeError("coverage graph published a non-coverage product")
        return (
            np.frombuffer(result.pixels, dtype=np.uint8)
            .reshape(
                result.height,
                result.width,
            )
            .copy()
        )


def _canonical_coverage(
    pixels: npt.NDArray[np.uint8],
) -> npt.NDArray[np.uint8]:
    """Validate and detach one two-dimensional Coverage8 field."""
    if pixels.dtype != np.uint8 or pixels.ndim != 2:
        raise TypeError("coverage pixels must be a two-dimensional uint8 array")
    return np.ascontiguousarray(pixels)


__all__ = ["NativeCoverageProjector"]
