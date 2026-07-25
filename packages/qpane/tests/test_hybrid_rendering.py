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
"""Public hybrid rendering and stable sampled-tile contracts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF, QRectF, QSize
from PySide6.QtGui import QColor, QImage, QTransform
from PySide6.QtWidgets import QApplication
from qpane import (
    HybridCombineMode,
    HybridDocument,
    HybridPresentationStyle,
    HybridRasterPrimitive,
    HybridSource,
    HybridVectorPrimitive,
    LayerTransform,
    QPane,
    RasterBounds,
    RenderLayer,
    RenderScene,
    VectorObject,
    VectorObjectKind,
    VectorShapeKind,
    VectorStyle,
)
from qpane.hybrid.evaluation import HybridDocumentEvaluator
from qpane.hybrid.tile_source import HybridRenderTileSource
from qpane.raster.image_conversion import (
    numpy_to_qimage_grayscale8_at_size,
    qimage_to_numpy_grayscale8,
)
from qpane.rendering.render_tile_geometry import visible_tile_requests
from qpane.rendering.scene_compiler import SceneRenderCompiler
from qpane.rendering.sdk_adapter import RenderSceneController
from qpane.scene.source_capabilities import LayerSourceCapabilities

from tests.harness.timing import interaction_clock, stable_latency_samples
from tests.helpers.execution_backend import TestExecution


@dataclass(frozen=True, slots=True)
class _SolidSampler:
    """Return constant grayscale coverage for requested output geometry."""

    value: int

    def sample(self, source_rect: QRectF, pixel_size: QSize) -> QImage:
        """Return one exact-size constant sample."""
        del source_rect
        pixels = np.full((1, 1), self.value, dtype=np.uint8)
        return numpy_to_qimage_grayscale8_at_size(pixels, pixel_size)


def test_hybrid_evaluator_combines_raster_and_vector_at_requested_density() -> None:
    """QPane must evaluate ordered raster and semantic vector content exactly."""
    vector = VectorObject(
        uuid.uuid4(),
        VectorObjectKind.SHAPE,
        (4.0, 4.0, 8.0, 8.0),
        LayerTransform(),
        VectorStyle(fill=QColor("white"), stroke=None),
        VectorShapeKind.RECTANGLE,
    )
    document = HybridDocument(
        uuid.uuid4(),
        RasterBounds(0, 0, 16, 16),
        (
            HybridRasterPrimitive(
                uuid.uuid4(),
                RasterBounds(0, 0, 16, 16),
                _SolidSampler(128),
            ),
            HybridVectorPrimitive(
                uuid.uuid4(),
                vector,
                RasterBounds(4, 4, 8, 8),
                HybridCombineMode.ADD,
            ),
        ),
        3,
    )

    image = HybridDocumentEvaluator().evaluate(
        document,
        QRectF(0.0, 0.0, 16.0, 16.0),
        QSize(32, 32),
    )
    pixels = qimage_to_numpy_grayscale8(image)

    assert pixels.shape == (32, 32)
    assert pixels[2, 2] == 128
    assert pixels[16, 16] == 255


def test_hybrid_source_uses_the_shared_scene_compiler_boundary() -> None:
    """Public hybrid sources must compile without masquerading as raster patches."""
    capabilities = LayerSourceCapabilities.create()
    controller = RenderSceneController(capabilities)
    document = HybridDocument(uuid.uuid4(), RasterBounds(-8, 4, 64, 48), revision=5)
    source = HybridSource(document, HybridPresentationStyle(QColor("cyan")), 2)
    scene = RenderScene.from_size(QSize(100, 80), (RenderLayer(source),))
    controller.set_scene(scene)
    contribution = controller.scene_contribution()

    assert contribution is not None
    compiler = SceneRenderCompiler(
        scene_provider=lambda: contribution.scene,
        revision_provider=controller.revision,
        source_metadata=capabilities.metadata,
        raster_sources=capabilities.rasters,
        vector_sources=capabilities.vectors,
        hybrid_sources=capabilities.hybrids,
    )
    compiled = compiler.compiled_scene()

    assert compiled is not None
    assert compiled.layers == ()
    assert compiled.vector_layers == ()
    assert tuple(layer.descriptor for layer in compiled.hybrid_layers) == (
        contribution.scene.layers
    )
    assert compiled.hybrid_layers[0].snapshot is source


def test_sampled_tile_identity_is_stable_across_viewport_motion() -> None:
    """Overlapping source tiles must retain identity when visible bounds shift."""
    source_id = uuid.uuid4()
    common = {
        "source_kind": "hybrid",
        "source_id": source_id,
        "revision_key": (7, 2),
        "fallback_key": RasterBounds(0, 0, 4096, 4096),
        "bounds": RasterBounds(0, 0, 4096, 4096),
        "panel_rect": QRectF(0.0, 0.0, 1024.0, 768.0),
        "device_pixel_ratio": 1.0,
        "budget_bytes": 32 * 1024 * 1024,
    }
    first = visible_tile_requests(
        source_to_panel=QTransform.fromScale(1.0, 1.0),
        **common,
    )
    shifted = QTransform.fromScale(1.0, 1.0)
    shifted.translate(-17.0, -11.0)
    second = visible_tile_requests(source_to_panel=shifted, **common)

    assert first is not None and second is not None
    first_keys = {request.key for request in first}
    second_keys = {request.key for request in second}
    assert first_keys & second_keys
    assert all(key.source_id == source_id for key in first_keys | second_keys)


def test_hybrid_tile_batch_evaluates_each_raster_sampler_once() -> None:
    """A visible batch must not repeat whole-document work for every tile."""
    calls: list[tuple[QRectF, QSize]] = []

    class RecordingSampler:
        """Return opaque coverage while recording requested batches."""

        def sample(self, source_rect: QRectF, pixel_size: QSize) -> QImage:
            """Record and return one exact grayscale sample."""
            calls.append((QRectF(source_rect), QSize(pixel_size)))
            image = QImage(pixel_size, QImage.Format.Format_Grayscale8)
            image.fill(255)
            return image

    source_id = uuid.uuid4()
    document = HybridDocument(
        source_id,
        RasterBounds(-300, 120, 2048, 1024),
        (
            HybridRasterPrimitive(
                uuid.uuid4(),
                RasterBounds(-300, 120, 2048, 1024),
                RecordingSampler(),
            ),
        ),
        revision=1,
    )
    source = HybridRenderTileSource(
        document,
        HybridPresentationStyle(QColor(30, 180, 220)),
    )
    requests = visible_tile_requests(
        source_kind=source.source_kind,
        source_id=source.source_id,
        revision_key=source.revision_key,
        fallback_key=source.fallback_key,
        bounds=source.bounds,
        source_to_panel=QTransform(),
        panel_rect=QRectF(0.0, 0.0, 1200.0, 700.0),
        device_pixel_ratio=1.0,
        budget_bytes=32 * 1024 * 1024,
    )

    assert requests is not None and len(requests) > 1
    products = source.render_tiles(requests, lambda: False)

    assert len(products) == len(requests)
    assert len(calls) == 1
    assert calls[0][0].x() == pytest.approx(-300.0)
    assert calls[0][0].y() == pytest.approx(120.0)
    assert all(product.image_source_rect.x() >= 0.0 for product in products)


def test_mounted_high_zoom_pan_never_exposes_unready_hybrid_vector_tiles(
    qapp: QApplication,
) -> None:
    """Guarded refinement must cover every frame while the next batch is held."""
    executor = TestExecution(auto_finish=False)
    pane = QPane(execution_runtime=executor.runtime)
    pane.resize(800, 600)
    bounds = RasterBounds(0, 0, 4096, 4096)
    geometry = VectorObject(
        uuid.uuid4(),
        VectorObjectKind.SHAPE,
        (0.0, 0.0, 4096.0, 4096.0),
        LayerTransform(),
        VectorStyle(fill=QColor("white"), stroke=None),
        VectorShapeKind.RECTANGLE,
    )
    source = HybridSource(
        HybridDocument(
            uuid.uuid4(),
            bounds,
            (HybridVectorPrimitive(uuid.uuid4(), geometry, bounds),),
            revision=1,
        ),
        HybridPresentationStyle(QColor(35, 195, 175)),
    )
    scene = RenderScene.from_size(QSize(4096, 4096), (RenderLayer(source),))
    sample_points = tuple(
        QPoint(x, y) for y in (40, 300, 560) for x in (32, 200, 400, 600, 768)
    )
    try:
        assert pane.setScene(scene, fit=False)
        pane.show()
        pane.applyZoom(4.0, QPointF(400.0, 300.0))
        qapp.processEvents()
        pane.calculateRenderPlan()
        assert (
            sum(
                job.operation.startswith("render.refinement")
                for job in executor.pending_jobs()
            )
            == 1
        )
        assert pane._rendering.presenter._render_refinement.pending_count == 3
        for _ in range(5):
            queued = sum(
                job.operation.startswith("render.refinement")
                for job in executor.pending_jobs()
            )
            if queued == 0:
                break
            executor.run_operation("render.refinement")
            qapp.processEvents()
        else:
            raise AssertionError("hybrid refinement did not settle")
        assert pane.calculateRenderPlan() is not None
        pane.update()
        qapp.processEvents()

        initial = pane.grab().toImage()
        assert all(
            _is_hybrid_tint(initial.pixelColor(point)) for point in sample_points
        )

        frame_samples: list[tuple[QColor, ...]] = []
        latencies = []
        metrics_before = pane._rendering.presenter.renderer.snapshot_metrics()
        for pan_x in (*range(0, 1801, 29), *range(1800, -1, -29)):
            started = interaction_clock()
            pane.setPan(QPointF(float(pan_x), 0.0))
            qapp.processEvents()
            frame = pane.grab().toImage()
            latencies.append((interaction_clock() - started) * 1000.0)
            frame_samples.append(
                tuple(frame.pixelColor(point) for point in sample_points)
            )

        assert frame_samples
        assert all(
            _is_hybrid_tint(color) for samples in frame_samples for color in samples
        )
        assert (
            sum(
                job.operation.startswith("render.refinement")
                for job in executor.pending_jobs()
            )
            == 1
        )
        assert len(executor.cancelled) < len(frame_samples) // 4
        metrics_after = pane._rendering.presenter.renderer.snapshot_metrics()
        assert metrics_after.scroll_hits - metrics_before.scroll_hits >= int(
            len(frame_samples) * 0.9
        )
        assert max(stable_latency_samples(latencies, parallel_batch_size=16)) < 16.0
        cache = pane._rendering.presenter._render_tile_cache
        assert 0 < cache.usage_bytes <= cache.budget_bytes
    finally:
        pane.clear()
        pane.close()
        pane.deleteLater()
        qapp.processEvents()


def _is_hybrid_tint(color: QColor) -> bool:
    """Return whether one presented pixel contains the opaque hybrid color."""
    return color.green() >= 185 and color.blue() >= 165 and color.red() <= 45
