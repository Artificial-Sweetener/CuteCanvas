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
"""Tests for mask geometry queries and scale-specific render derivation."""

from __future__ import annotations

import uuid

import numpy as np
from cutecanvas import Config
from cutecanvas.core.config_features import MaskConfigSlice
from cutecanvas.coverage import (
    CoverageCombineMode,
    CoverageGeometryFactory,
    VectorCoverageItem,
)
from cutecanvas.masks.live_preview_store import MaskLivePreviewStore
from cutecanvas.masks.mask import MaskAssetStore
from cutecanvas.masks.mask_controller import MaskController
from cutecanvas.masks.mask_undo import (
    MaskHistoryChange,
    MaskImageCommand,
    MaskUndoSnippet,
)
from cutecanvas.masks.source_resolver import MaskSourceCapabilities
from cutecanvas.resources import ProjectResourceReference, ProjectResourceStore
from PySide6.QtCore import QPointF, QRect, QRectF, QSize
from PySide6.QtGui import QColor, QImage
from qpane.hybrid.evaluation import HybridDocumentEvaluator
from qpane.raster.image_conversion import qimage_to_numpy_grayscale8
from qpane.scene.raster import RasterBounds

from qpane import HybridPresentationStyle, HybridSource, LayerTransform


def test_preview_stride_defaults_to_visible_density_before_cache_warmup(qapp) -> None:
    """A fresh mask must not build a native-resolution preview unnecessarily."""
    assets = MaskAssetStore(ProjectResourceStore())
    image = QImage(4096, 4096, QImage.Format.Format_Grayscale8)
    image.fill(0)
    mask_id = assets.create_mask(image)
    layer = assets.get_layer(mask_id)
    assert layer is not None
    controller = MaskController(
        assets,
        source_to_panel_point=lambda point: QPointF(point),
        config=Config(),
        mask_config=MaskConfigSlice(),
        live_previews=MaskLivePreviewStore(),
    )

    assert controller.renders.preview_stride(mask_id, 0.125) == 8

    controller.renders.get_best_by_id(mask_id, scale=0.5)

    assert controller.renders.preview_stride(mask_id, 0.125) == 2


def test_preview_stride_stays_native_for_compact_offset_storage(qapp) -> None:
    """Compact storage must use coordinate-aware native preview patches."""
    assets = MaskAssetStore(ProjectResourceStore())
    image = QImage(4096, 4096, QImage.Format.Format_Grayscale8)
    image.fill(0)
    image.setPixelColor(2048, 1024, QColor(255, 255, 255))
    mask_id = assets.create_mask_from_image(image)
    layer = assets.get_layer(mask_id)
    assert layer is not None
    assert layer.coverage.compact_raster_storage()
    assert layer.coverage.raster.bounds == RasterBounds(2048, 1024, 1, 1)
    controller = MaskController(
        assets,
        source_to_panel_point=lambda point: QPointF(point),
        config=Config(),
        mask_config=MaskConfigSlice(),
        live_previews=MaskLivePreviewStore(),
    )

    assert controller.renders.preview_stride(mask_id, 0.125) == 1


def test_native_live_preview_reframe_preserves_prior_patches(qapp) -> None:
    """Sparse growth must not discard already presented stroke coverage."""
    store = MaskLivePreviewStore()
    mask_id = uuid.uuid4()
    first = QImage(2, 2, QImage.Format.Format_Grayscale8)
    first.fill(80)
    store.apply_patch(
        mask_id,
        RasterBounds(10, 20, 8, 8),
        QRect(1, 1, 2, 2),
        first,
    )
    preview = store.preview(mask_id)
    assert preview is not None
    session_id = preview.session_id

    second = QImage(2, 2, QImage.Format.Format_Grayscale8)
    second.fill(160)
    store.apply_patch(
        mask_id,
        RasterBounds(5, 15, 20, 20),
        QRect(10, 10, 2, 2),
        second,
    )

    reframed = store.preview(mask_id)
    assert reframed is preview
    assert reframed.session_id == session_id
    pixels = np.zeros((20, 20), dtype=np.uint8)
    reframed.apply_to(RasterBounds(5, 15, 20, 20), pixels)
    assert np.all(pixels[6:8, 6:8] == 80)
    assert np.all(pixels[10:12, 10:12] == 160)


def test_live_preview_patches_preserve_durable_offset_coverage(qapp) -> None:
    """A new preview session must overlay rather than replace durable coverage."""
    assets = MaskAssetStore(ProjectResourceStore())
    image = QImage(96, 72, QImage.Format.Format_Grayscale8)
    image.fill(0)
    for y in range(10, 20):
        for x in range(10, 20):
            image.setPixelColor(x, y, QColor(120, 120, 120))
    mask_id = assets.create_mask_from_image(image)
    layer = assets.get_layer(mask_id)
    assert layer is not None
    assert layer.coverage.compact_raster_storage()
    assert layer.coverage.raster.bounds == RasterBounds(10, 10, 10, 10)
    writable = layer.coverage.raster.ensure_writable(RasterBounds(10, 10, 50, 40))
    assert writable.after_bounds == RasterBounds(10, 10, 50, 40)
    storage_rect = layer.coverage.raster.storage_rect(RasterBounds(50, 40, 5, 5))
    assert storage_rect is not None
    live_previews = MaskLivePreviewStore()
    patch = QImage(5, 5, QImage.Format.Format_Grayscale8)
    patch.fill(255)
    live_previews.apply_patch(
        mask_id,
        writable.after_bounds,
        storage_rect.to_qrect(),
        patch,
    )
    bounds = RasterBounds(0, 0, 96, 72)
    pixels = layer.coverage.snapshot(bounds).pixels.copy()
    preview = live_previews.preview(mask_id)
    assert preview is not None
    preview.apply_to(bounds, pixels)
    assert pixels[15, 15] == 120
    assert pixels[42, 52] == 255


def test_scaled_mask_render_does_not_materialize_full_surface(
    qapp, monkeypatch
) -> None:
    """Fit-scale rendering should copy only decimated authoritative pixels."""
    assets = MaskAssetStore(ProjectResourceStore())
    image = QImage(64, 48, QImage.Format.Format_Grayscale8)
    image.fill(255)
    mask_id = assets.create_mask(image)
    layer = assets.get_layer(mask_id)
    assert layer is not None
    controller = MaskController(
        assets,
        source_to_panel_point=lambda point: QPointF(point),
        config=Config(),
        mask_config=MaskConfigSlice(),
        live_previews=MaskLivePreviewStore(),
    )
    resolver = MaskSourceCapabilities(assets=assets, renders=controller.renders)

    def reject_full_snapshot() -> QImage:
        raise AssertionError("scaled rendering requested a full mask snapshot")

    monkeypatch.setattr(layer.coverage.raster, "snapshot_qimage", reject_full_snapshot)

    assert resolver.source_size(ProjectResourceReference(mask_id)) == QSize(64, 48)
    pixmap = controller.renders.get(layer, scale=0.25)

    assert pixmap is not None
    assert pixmap.size() == QSize(16, 12)


def test_worker_colorized_mask_patch_does_not_materialize_full_surface(
    qapp,
    monkeypatch,
) -> None:
    """Adopting a prepared patch must not copy pixels that the worker replaced."""
    assets = MaskAssetStore(ProjectResourceStore())
    image = QImage(8192, 8192, QImage.Format.Format_Grayscale8)
    image.fill(255)
    mask_id = assets.create_mask(image)
    layer = assets.get_layer(mask_id)
    assert layer is not None
    controller = MaskController(
        assets,
        source_to_panel_point=lambda point: QPointF(point),
        config=Config(),
        mask_config=MaskConfigSlice(),
        live_previews=MaskLivePreviewStore(),
    )
    dirty_rect = QRect(2048, 2048, 1024, 1024)
    colorized = QImage(dirty_rect.size(), QImage.Format.Format_ARGB32_Premultiplied)
    colorized.fill(QColor(30, 170, 220, 140))

    def reject_full_snapshot() -> QImage:
        raise AssertionError("prepared patch adoption copied the full mask")

    monkeypatch.setattr(layer.coverage.raster, "snapshot_qimage", reject_full_snapshot)

    controller.renders.update_region(
        dirty_rect,
        layer,
        colorized_image=colorized,
    )


def test_history_delta_reads_only_dirty_surface_regions(qapp, monkeypatch) -> None:
    """Undo presentation must not copy a large authoritative mask in full."""

    assets = MaskAssetStore(ProjectResourceStore())
    image = QImage(4096, 4096, QImage.Format.Format_Grayscale8)
    image.fill(0)
    mask_id = assets.create_mask(image)
    layer = assets.get_layer(mask_id)
    assert layer is not None
    controller = MaskController(
        assets,
        source_to_panel_point=lambda point: QPointF(point),
        config=Config(),
        mask_config=MaskConfigSlice(),
        live_previews=MaskLivePreviewStore(),
    )
    assert controller.renders.get(layer, scale=0.125) is not None
    dirty = QRect(1024, 768, 48, 32)
    layer.coverage.raster.mutate_storage_region(
        RasterBounds.from_qrect(dirty),
        lambda pixels, _image: pixels.fill(255),
    )
    original_snapshot_region = layer.coverage.raster.snapshot_storage_region
    captured_regions: list[RasterBounds] = []

    def reject_full_snapshot() -> QImage:
        raise AssertionError("history presentation copied the full mask")

    def capture_region(region: RasterBounds, *, stride: int = 1) -> np.ndarray:
        captured_regions.append(region)
        return original_snapshot_region(region, stride=stride)

    monkeypatch.setattr(layer.coverage.raster, "snapshot_qimage", reject_full_snapshot)
    monkeypatch.setattr(
        layer.coverage.raster,
        "snapshot_storage_region",
        capture_region,
    )
    snippet = QImage(dirty.size(), QImage.Format.Format_Grayscale8)
    snippet.fill(255)
    command = MaskImageCommand(mask_id, QImage(), QImage(), lambda _id, _image: None)

    assert controller.renders.apply_history_delta(
        layer,
        MaskHistoryChange(
            mask_id,
            "undo",
            command,
            (MaskUndoSnippet(dirty, snippet),),
        ),
    )
    assert captured_regions == [RasterBounds.from_qrect(dirty)]


def test_native_live_preview_uses_document_shared_transient_coverage(
    qapp,
) -> None:
    """Native stroke feedback must bypass durable source products."""
    assets = MaskAssetStore(ProjectResourceStore())
    image = QImage(64, 48, QImage.Format.Format_Grayscale8)
    image.fill(0)
    mask_id = assets.create_mask(image)
    layer = assets.get_layer(mask_id)
    assert layer is not None
    config = Config()
    config.configure(cache={"mode": "hard", "budget_mb": 64})
    controller = MaskController(
        assets,
        source_to_panel_point=lambda point: QPointF(point),
        config=config,
        mask_config=MaskConfigSlice(),
        live_previews=MaskLivePreviewStore(),
    )
    fit_pixmap = controller.renders.get(layer, scale=0.5)
    assert fit_pixmap is not None
    assert controller.renders.cache_usage_bytes > 0

    dirty_rect = QRect(8, 8, 8, 8)
    preview = QImage(dirty_rect.size(), QImage.Format.Format_Grayscale8)
    preview.fill(255)
    preview.setText("qpane_preview_stride", "1")
    preview.setText("qpane_preview_provisional", "1")
    controller.renders.update_region(dirty_rect, layer, sub_mask_image=preview)
    adjacent_rect = QRect(16, 8, 8, 8)
    controller.renders.update_region(
        adjacent_rect,
        layer,
        sub_mask_image=preview,
    )

    patches = MaskSourceCapabilities(
        assets=assets,
        renders=controller.renders,
    ).source_patches(
        ProjectResourceReference(mask_id),
        RasterBounds(8, 8, 16, 8),
    )

    assert patches is None
    shared = controller.renders.live_preview_patches(mask_id)
    assert shared is not None
    bounds = RasterBounds(8, 8, 16, 8)
    pixels = np.zeros((bounds.height, bounds.width), dtype=np.uint8)
    shared.apply_to(bounds, pixels)
    assert np.all(pixels == 255)


def test_oversized_sparse_mask_live_dot_never_snapshots_its_full_storage(
    qapp,
    monkeypatch,
) -> None:
    """A native live dot must cost only its sampled region, not the mask envelope."""
    assets = MaskAssetStore(ProjectResourceStore())
    image = QImage(64, 48, QImage.Format.Format_Grayscale8)
    image.fill(0)
    mask_id = assets.create_mask(image)
    layer = assets.get_layer(mask_id)
    assert layer is not None
    surface = layer.coverage.raster
    oversized = RasterBounds(-3840, -2688, 7680, 10752)
    assert surface.set_bounds(oversized)
    controller = MaskController(
        assets,
        source_to_panel_point=lambda point: QPointF(point),
        config=Config(),
        mask_config=MaskConfigSlice(),
        live_previews=MaskLivePreviewStore(),
    )
    resolver = MaskSourceCapabilities(assets=assets, renders=controller.renders)
    dirty_rect = QRect(4096, 3072, 32, 24)
    preview = QImage(dirty_rect.size(), QImage.Format.Format_Grayscale8)
    preview.fill(255)
    preview.setText("qpane_preview_stride", "1")
    preview.setText("qpane_preview_provisional", "1")

    def reject_dense_snapshot(
        _region: RasterBounds,
        *,
        stride: int = 1,
    ) -> np.ndarray:
        del stride
        raise AssertionError("live preview materialized mask storage")

    monkeypatch.setattr(surface, "snapshot_storage_region", reject_dense_snapshot)

    controller.renders.update_region(dirty_rect, layer, sub_mask_image=preview)
    visible = RasterBounds(
        oversized.x + dirty_rect.x(),
        oversized.y + dirty_rect.y(),
        dirty_rect.width(),
        dirty_rect.height(),
    )
    patches = resolver.source_patches(
        ProjectResourceReference(mask_id),
        visible,
    )

    assert patches is None
    shared = controller.renders.live_preview_patches(mask_id)
    assert shared is not None
    pixels = np.zeros((visible.height, visible.width), dtype=np.uint8)
    shared.apply_to(visible, pixels)
    assert np.all(pixels == 255)


def test_retained_mask_publishes_hybrid_source_without_visible_patch_evaluation(
    qapp,
    monkeypatch,
) -> None:
    """Frame planning must not synchronously rasterize retained mask geometry."""
    assets = MaskAssetStore(ProjectResourceStore())
    image = QImage(2048, 2048, QImage.Format.Format_Grayscale8)
    image.fill(0)
    mask_id = assets.create_mask(image)
    layer = assets.get_layer(mask_id)
    assert layer is not None
    layer.coverage.append(
        VectorCoverageItem(
            uuid.uuid4(),
            CoverageGeometryFactory().rectangle(QRectF(128.0, 96.0, 1500.0, 1200.0)),
        )
    )
    controller = MaskController(
        assets,
        source_to_panel_point=lambda point: QPointF(point),
        config=Config(),
        mask_config=MaskConfigSlice(),
        live_previews=MaskLivePreviewStore(),
    )
    resolver = MaskSourceCapabilities(assets=assets, renders=controller.renders)
    source = ProjectResourceReference(mask_id)

    monkeypatch.setattr(
        layer.coverage,
        "snapshot",
        lambda _bounds=None: (_ for _ in ()).throw(
            AssertionError("frame planning evaluated retained coverage")
        ),
    )

    hybrid = resolver.hybrid_document(source)
    controller.renders.warm(mask_id)

    assert isinstance(hybrid, HybridSource)
    assert controller.renders.prepare_image(layer) is None
    assert controller.renders.prepare_image_detached(layer) is None
    assert (
        resolver.source_patches(
            source,
            RasterBounds(37, 41, 1024, 768),
        )
        == ()
    )
    assert hybrid.document.bounds == RasterBounds(0, 0, 2048, 2048)


def test_qpane_hybrid_evaluation_matches_authoritative_mask_algebra(qapp) -> None:
    """The shared renderer must preserve transforms, feather, and combine order."""
    assets = MaskAssetStore(ProjectResourceStore())
    image = QImage(96, 72, QImage.Format.Format_Grayscale8)
    image.fill(0)
    for y in range(14, 52):
        for x in range(10, 54):
            image.setPixelColor(x, y, QColor(140, 140, 140))
    mask_id = assets.create_mask(image)
    layer = assets.get_layer(mask_id)
    assert layer is not None
    geometry = CoverageGeometryFactory()
    assert layer.coverage.append(
        VectorCoverageItem(
            uuid.uuid4(),
            geometry.ellipse(QRectF(18.0, 8.0, 52.0, 44.0)),
            CoverageCombineMode.ADD,
            LayerTransform(dx=7.5, dy=5.25),
            1.5,
        )
    )
    assert layer.coverage.append(
        VectorCoverageItem(
            uuid.uuid4(),
            geometry.rectangle(QRectF(38.0, 18.0, 25.0, 31.0)),
            CoverageCombineMode.SUBTRACT,
        )
    )
    bounds = layer.coverage.source_bounds()
    assert bounds is not None
    expected = layer.coverage.snapshot(bounds).pixels
    hybrid = MaskSourceCapabilities(
        assets=assets,
        renders=MaskController(
            assets,
            source_to_panel_point=lambda point: QPointF(point),
            config=Config(),
            mask_config=MaskConfigSlice(),
            live_previews=MaskLivePreviewStore(),
        ).renders,
    ).hybrids.source(
        layer,
        HybridPresentationStyle(QColor("cyan")),
        1,
    )
    assert hybrid is not None

    rendered = HybridDocumentEvaluator().evaluate(
        hybrid.document,
        QRectF(
            float(bounds.x),
            float(bounds.y),
            float(bounds.width),
            float(bounds.height),
        ),
        QSize(bounds.width, bounds.height),
    )

    actual = qimage_to_numpy_grayscale8(rendered)
    actual_nonzero = np.argwhere(actual != 0)
    expected_nonzero = np.argwhere(expected != 0)
    assert np.array_equal(actual, expected), (
        int(np.count_nonzero(actual != expected)),
        int(np.max(np.abs(actual.astype(np.int16) - expected.astype(np.int16)))),
        (actual_nonzero.min(0), actual_nonzero.max(0)),
        (expected_nonzero.min(0), expected_nonzero.max(0)),
        (actual[30, 45], expected[30, 45]),
        (actual[20, 30], expected[20, 30]),
    )
