#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Behavioral performance safeguards for cached editor feedback geometry."""

from __future__ import annotations

import uuid

import numpy as np
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from qpane.coverage import CoverageSnapshot
from qpane.scene.raster import RasterBounds, RasterExtentPolicy
from qpane.selection import PixelSelectionState, SelectionBoundaryBuilder
from qpane.ui.editor_overlays import PixelSelectionOverlayRenderer


def test_translated_selection_reuses_cached_boundary_topology(
    qapp: QApplication,
    monkeypatch,
) -> None:
    """Pointer translation must not rebuild unchanged marching-ant topology."""
    del qapp
    pixels = np.zeros((1000, 1000), dtype=np.uint8)
    pixels[::4, 100:900] = 255
    coverage = CoverageSnapshot(
        RasterBounds(20, 30, 1000, 1000),
        RasterExtentPolicy.EXPAND_ON_WRITE,
        pixels,
    )
    build_calls = 0
    original_build = SelectionBoundaryBuilder.build

    def counted_build(self, snapshot, *, threshold=128):
        """Record expensive topology extraction while preserving production work."""
        nonlocal build_calls
        build_calls += 1
        return original_build(self, snapshot, threshold=threshold)

    monkeypatch.setattr(SelectionBoundaryBuilder, "build", counted_build)
    parent = QObject()
    renderer = PixelSelectionOverlayRenderer(lambda: None, parent)
    scene_id = uuid.uuid4()

    renderer.set_state(PixelSelectionState(scene_id, 1, coverage))
    for revision in range(2, 20):
        renderer.set_state(
            PixelSelectionState(
                scene_id,
                revision,
                coverage.translated(revision * 3, revision * -2),
            )
        )

    assert build_calls == 1
    parent.deleteLater()
