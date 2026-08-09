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

"""Contract tests for demand-aware sampled transition compilation."""

from __future__ import annotations

import uuid
from dataclasses import replace

import numpy as np
from cutecanvas.rendering.raster_transitions import RasterTransitionRenderCompiler
from cutecanvas.scene.pixel_fragments import RasterPixelFormat
from cutecanvas.scene.pixel_transitions import RasterPixelTransition
from cutecanvas.scene.source_capabilities import (
    PixelPresentationOwner,
    PixelSampleGeometry,
)
from cutecanvas_test_support.render_plan import make_render_plan
from PySide6.QtCore import QRect, QRectF, QSize
from PySide6.QtGui import QColor, QImage, QTransform
from qpane.scene.raster import RasterBounds
from qpane.scene.render_plan import (
    SampledLayerRenderItem,
    SampledTileRenderData,
    TransientRasterResolvedContribution,
    TransientSampledResolvedContribution,
)
from qpane.sdk.scene import LayerSourceReference


class _RecordingPresentations(PixelPresentationOwner):
    """Return exact samples while recording the products requested each time."""

    def __init__(self) -> None:
        """Initialize without any presentation calls."""
        self.calls: list[tuple[PixelSampleGeometry, ...]] = []
        self.fallback_calls: list[QSize] = []

    def present_transition_samples(
        self,
        source: LayerSourceReference,
        pixel_format: RasterPixelFormat,
        transition: RasterPixelTransition,
        samples: tuple[PixelSampleGeometry, ...],
    ) -> tuple[QImage, ...]:
        """Return detached products for exactly the requested missing samples."""
        del source, pixel_format, transition
        self.calls.append(samples)
        products = []
        for sample in samples:
            image = QImage(sample.pixel_size, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(QColor(255, 0, 0, 100))
            products.append(image)
        return tuple(products)

    def present_pixels(
        self,
        source: LayerSourceReference,
        pixel_format: RasterPixelFormat,
        pixels: np.ndarray,
        target_size: QSize | None = None,
    ) -> QImage:
        """Return one bounded fallback patch and record its requested size."""
        del source, pixel_format, pixels
        size = target_size or QSize(1, 1)
        self.fallback_calls.append(QSize(size))
        image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor(255, 0, 0, 100))
        return image


def test_sampled_transition_reuses_overlap_and_resolves_new_or_refined_tiles() -> None:
    """Demand changes must reuse overlap and resolve every changed source product."""
    presentations = _RecordingPresentations()
    compiler = RasterTransitionRenderCompiler(presentations)
    first, retained, incoming = _sample_tiles()
    initial_item = _sampled_item((first, retained))
    session_id = uuid.uuid4()
    transition = _transition()

    initial = compiler.compile(
        session_id=session_id,
        scene_id=initial_item.descriptor.scene_id,
        layer_id=initial_item.descriptor.layer_id,
        pixel_format=RasterPixelFormat.COVERAGE8,
        transition=transition,
        generation=1,
        item=initial_item,
        retain_until_durable=False,
    )
    panned_item = replace(initial_item, tiles=(retained, incoming))
    panned = compiler.compile(
        session_id=session_id,
        scene_id=panned_item.descriptor.scene_id,
        layer_id=panned_item.descriptor.layer_id,
        pixel_format=RasterPixelFormat.COVERAGE8,
        transition=transition,
        generation=1,
        item=panned_item,
        retain_until_durable=False,
    )
    refined_image = QImage(retained.image.size(), retained.image.format())
    refined_image.fill(QColor(10, 20, 30, 255))
    refined = replace(retained, image=refined_image)
    refined_item = replace(panned_item, tiles=(refined, incoming))
    refined_result = compiler.compile(
        session_id=session_id,
        scene_id=refined_item.descriptor.scene_id,
        layer_id=refined_item.descriptor.layer_id,
        pixel_format=RasterPixelFormat.COVERAGE8,
        transition=transition,
        generation=1,
        item=refined_item,
        retain_until_durable=False,
    )

    assert initial is not None
    assert panned is not None
    assert refined_result is not None
    assert isinstance(initial, TransientSampledResolvedContribution)
    assert isinstance(panned, TransientSampledResolvedContribution)
    assert isinstance(refined_result, TransientSampledResolvedContribution)
    assert tuple(len(call) for call in presentations.calls) == (2, 1, 1)
    assert panned.sample_geometry_key == panned_item.sample_geometry_key
    assert refined_result.sample_geometry_key == refined_item.sample_geometry_key
    assert panned.tiles[0].image.cacheKey() == initial.tiles[1].image.cacheKey()
    assert refined_result.tiles[1].image.cacheKey() == panned.tiles[1].image.cacheKey()
    assert presentations.fallback_calls == []


def test_transition_outside_current_sampled_tiles_uses_a_bounded_patch() -> None:
    """Incomplete demand must not publish a sampled batch that omits the edit."""
    presentations = _RecordingPresentations()
    compiler = RasterTransitionRenderCompiler(presentations)
    first, _retained, _incoming = _sample_tiles()
    item = _sampled_item((first,))
    patch = RasterBounds(128, 8, 16, 16)
    surface = RasterBounds(0, 0, 192, 64)
    transition = RasterPixelTransition(
        patch,
        surface,
        surface,
        np.zeros((16, 16), dtype=np.uint8),
        np.full((16, 16), 255, dtype=np.uint8),
    )

    result = compiler.compile(
        session_id=uuid.uuid4(),
        scene_id=item.descriptor.scene_id,
        layer_id=item.descriptor.layer_id,
        pixel_format=RasterPixelFormat.COVERAGE8,
        transition=transition,
        generation=1,
        item=item,
    )

    assert isinstance(result, TransientRasterResolvedContribution)
    assert result.source_bounds == patch
    assert presentations.calls == []
    assert presentations.fallback_calls == [QSize(16, 16)]


def _sampled_item(
    tiles: tuple[SampledTileRenderData, ...],
) -> SampledLayerRenderItem:
    """Return one sampled render item using stable test scene identity."""
    plan = make_render_plan(QRect(0, 0, 128, 64))
    raster_item = plan.render_items[0]
    bounds = RasterBounds(0, 0, 192, 64)
    descriptor = replace(raster_item.descriptor, raster_bounds=bounds)
    return SampledLayerRenderItem(
        descriptor=descriptor,
        transform=QTransform(),
        placement=descriptor.placement,
        clip=descriptor.clip,
        source_size=QSize(192, 64),
        render_hint_enabled=False,
        tiles=tiles,
    )


def _sample_tiles() -> tuple[
    SampledTileRenderData,
    SampledTileRenderData,
    SampledTileRenderData,
]:
    """Return three neighboring immutable source products."""
    tiles = []
    for column in range(3):
        image = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor(20 + column, 40, 60, 255))
        tiles.append(
            SampledTileRenderData(
                image,
                QRectF(float(column * 64), 0.0, 64.0, 64.0),
                QRectF(0.0, 0.0, 64.0, 64.0),
            )
        )
    return tiles[0], tiles[1], tiles[2]


def _transition() -> RasterPixelTransition:
    """Return one immutable coverage edit spanning the sampled surface."""
    patch = RasterBounds(64, 0, 16, 16)
    surface = RasterBounds(0, 0, 192, 64)
    before = np.zeros((16, 16), dtype=np.uint8)
    after = np.full((16, 16), 255, dtype=np.uint8)
    return RasterPixelTransition(patch, surface, surface, before, after)
