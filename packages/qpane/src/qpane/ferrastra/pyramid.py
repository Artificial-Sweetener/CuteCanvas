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

"""Produce exact QPane pyramid levels through canonical Ferrastra graphs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from PySide6.QtGui import QImage

from ferrastra import CancellationToken as NativeCancellationToken
from ferrastra import (
    Engine,
    EvaluationBudget,
    Graph,
    GraphBuilder,
    RasterReconstructionSpace,
    Region,
)
from qpane.ferrastra.qimage import qimage_from_rgba8, qimage_to_rgba8


class _CancellationBridge(Protocol):
    """Describe the QPane-owned cancellation behavior needed by native work."""

    def raise_if_cancelled(self) -> None:
        """Raise the QPane cancellation reason after cancellation."""
        ...

    def subscribe(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Bridge cancellation into one bounded native request."""
        ...


@dataclass(frozen=True)
class ExactPyramidLevels:
    """Contain detached exact levels and their retained byte count."""

    levels: dict[float, QImage]
    size_bytes: int


def generate_exact_pyramid_levels(
    image: QImage,
    min_view_size_px: int,
    cancellation: _CancellationBridge,
    *,
    reconstruction_space: RasterReconstructionSpace = (
        RasterReconstructionSpace.SRGB_ENCODED
    ),
) -> ExactPyramidLevels:
    """Evaluate each exact half-scale product from one retained source revision."""
    cancellation.raise_if_cancelled()
    source = qimage_to_rgba8(image)
    engine = Engine()
    revision = engine.add_rgba8(
        source.pixels,
        source.width,
        source.height,
        stride_bytes=source.stride_bytes,
    )
    native_cancellation = NativeCancellationToken()
    unsubscribe = cancellation.subscribe(native_cancellation.cancel)
    levels: dict[float, QImage] = {}
    try:
        for scale, width, height in _level_sizes(
            source.width,
            source.height,
            min_view_size_px,
        ):
            cancellation.raise_if_cancelled()
            graph = _resize_graph(
                revision,
                (source.width, source.height),
                (width, height),
                reconstruction_space,
            )
            compiled = engine.compile(graph)
            region = Region(0, 0, width, height)
            requirements = engine.requirements(compiled, "result", region)
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
            levels[scale] = qimage_from_rgba8(
                result.pixels,
                result.width,
                result.height,
                result.stride_bytes,
            )
    finally:
        unsubscribe()
    cancellation.raise_if_cancelled()
    return ExactPyramidLevels(
        levels=levels,
        size_bytes=sum(level.sizeInBytes() for level in levels.values()),
    )


def _resize_graph(
    revision: str,
    source_size: tuple[int, int],
    destination_size: tuple[int, int],
    reconstruction_space: RasterReconstructionSpace,
) -> Graph:
    """Build one exact source-to-resize graph for a destination level."""
    builder = GraphBuilder(1)
    builder.add_node(1, "ferrastra.source.raster")
    builder.set_source_revision(1, revision)
    builder.add_node(2, "ferrastra.resample.lanczos3")
    builder.connect(1, "result", 2, "source")
    for parameter, value in (
        ("source_width", source_size[0]),
        ("source_height", source_size[1]),
        ("destination_width", destination_size[0]),
        ("destination_height", destination_size[1]),
    ):
        builder.set_integer(2, parameter, value)
    builder.set_enum(2, "edge_mode", "clamp")
    builder.set_enum(2, "working_space", reconstruction_space.value)
    builder.add_output("result", 2)
    return builder.build()


def _level_sizes(
    width: int,
    height: int,
    min_view_size_px: int,
) -> list[tuple[float, int, int]]:
    """Return QPane's canonical descending half-scale level dimensions."""
    minimum = max(1, int(min_view_size_px))
    scale = 1.0
    level_width = width
    level_height = height
    levels: list[tuple[float, int, int]] = []
    while max(level_width, level_height) > minimum:
        scale /= 2.0
        level_width = int(width * scale)
        level_height = int(height * scale)
        if level_width <= 0 or level_height <= 0:
            break
        levels.append((scale, level_width, level_height))
    return levels


__all__ = ["ExactPyramidLevels", "generate_exact_pyramid_levels"]
