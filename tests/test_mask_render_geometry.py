#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Tests for mask geometry queries and scale-specific render derivation."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QSize
from PySide6.QtGui import QImage

from qpane import Config
from qpane.core.config_features import MaskConfigSlice
from qpane.masks.mask import MaskAssetStore
from qpane.masks.mask_controller import MaskController
from qpane.masks.source_reference import MaskAssetReference
from qpane.masks.source_resolver import MaskSourceCapabilities


def test_scaled_mask_render_does_not_materialize_full_surface(
    qapp, monkeypatch
) -> None:
    """Fit-scale rendering should copy only decimated authoritative pixels."""
    assets = MaskAssetStore()
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

    monkeypatch.setattr(layer.surface, "snapshot_qimage", reject_full_snapshot)

    assert resolver.source_size(MaskAssetReference(mask_id)) == QSize(64, 48)
    pixmap = controller.renders.get(layer, scale=0.25)

    assert pixmap is not None
    assert pixmap.size() == QSize(16, 12)


def test_live_preview_reuses_nearest_cache_during_scale_transition(qapp) -> None:
    """A stroke stays visible while the requested viewport scale changes."""
    assets = MaskAssetStore()
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

    live_pixmap = controller.renders.get(layer, scale=1.0)

    assert live_pixmap is fit_pixmap
    assert live_pixmap.toImage().pixelColor(5, 5).alpha() > 0
