#    QPane + CuteCanvas - High-performance PySide6 rendering and editing
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
from cutecanvas.masks.mask import MaskAssetStore
from cutecanvas.masks.mask_controller import MaskController
from cutecanvas.masks.source_resolver import MaskSourceCapabilities
from cutecanvas.resources import ProjectResourceReference, ProjectResourceStore
from PySide6.QtCore import QPointF, QRect, QRectF, QSize
from PySide6.QtGui import QColor, QImage
from qpane import HybridPresentationStyle, HybridSource, LayerTransform
from qpane.hybrid.evaluation import HybridDocumentEvaluator
from qpane.raster.image_conversion import qimage_to_numpy_grayscale8
from qpane.scene.raster import RasterBounds


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
    )

    assert controller.renders.preview_stride(mask_id, 0.125) == 8

    controller.renders.get_best_by_id(mask_id, scale=0.5)

    assert controller.renders.preview_stride(mask_id, 0.125) == 2


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


def test_live_preview_uses_one_exact_sample_lattice_during_scale_transition(
    qapp,
) -> None:
    """A stroke must not resample independent patches into another cache density."""
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

    live_pixmap = controller.renders.get(layer, scale=1.0)

    assert live_pixmap is not fit_pixmap
    assert live_pixmap is not None
    assert live_pixmap.size() == image.size()
    assert live_pixmap.toImage().pixelColor(8, 8).alpha() > 0
    row = tuple(
        live_pixmap.toImage().pixelColor(x_position, 12).rgba()
        for x_position in range(8, 24)
    )
    assert len(set(row)) == 1


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
