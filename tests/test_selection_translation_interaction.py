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
"""Selection-only translation interaction and history behavior."""

from __future__ import annotations

import uuid

import numpy as np
from cutecanvas.coverage import CoverageSnapshot
from cutecanvas.selection.history import PixelSelectionEdit
from cutecanvas.selection.service import PixelSelectionService
from cutecanvas.selection.translation_interaction import (
    PixelSelectionTranslationInteraction,
)
from cutecanvas.types import RasterExtentPolicy
from PySide6.QtCore import QPointF
from qpane.sdk.scene import LayerPlacement, RasterBounds, SceneDescriptor, SceneKind


def _interaction(
    edits: list[PixelSelectionEdit],
) -> tuple[
    uuid.UUID,
    PixelSelectionService,
    PixelSelectionTranslationInteraction,
]:
    """Build an active scene with hard coverage and a recording history port."""
    scene_id = uuid.uuid4()
    scene = SceneDescriptor(
        scene_id,
        SceneKind.EXPLICIT,
        LayerPlacement(0.0, 0.0, 40.0, 30.0),
        (),
    )
    selections = PixelSelectionService(record_edit=edits.append)
    selections.replace_with_raster(
        scene_id,
        CoverageSnapshot(
            RasterBounds(4, 5, 6, 7),
            RasterExtentPolicy.EXPAND_ON_WRITE,
            np.full((7, 6), 255, dtype=np.uint8),
        ),
    )
    edits.clear()
    return (
        scene_id,
        selections,
        PixelSelectionTranslationInteraction(
            active_scene=lambda: scene,
            selections=selections,
        ),
    )


def test_translation_previews_bounds_without_copying_or_moving_content() -> None:
    """Dragging should translate selection coordinates and retain pixel storage."""
    edits: list[PixelSelectionEdit] = []
    scene_id, selections, interaction = _interaction(edits)
    before = selections.state(scene_id).coverage
    assert before is not None

    assert interaction.begin(QPointF(6.0, 7.0))
    assert interaction.update(QPointF(11.0, 4.0))

    preview = selections.state(scene_id).coverage
    assert preview is not None
    assert preview.bounds == RasterBounds(9, 2, 6, 7)
    assert preview.pixels is before.pixels
    assert not edits

    assert interaction.finish(QPointF(11.0, 4.0))
    assert len(edits) == 1
    assert selections.undo_edit(edits[0])
    restored = selections.state(scene_id).coverage
    assert restored is not None
    assert restored.bounds == RasterBounds(4, 5, 6, 7)


def test_translation_requires_covered_pixel_and_cancel_restores_preview() -> None:
    """Transparent misses author normally while Escape restores the prior boundary."""
    edits: list[PixelSelectionEdit] = []
    scene_id, selections, interaction = _interaction(edits)

    assert not interaction.begin(QPointF(20.0, 20.0))
    assert interaction.begin(QPointF(5.0, 6.0))
    assert interaction.update(QPointF(8.0, 10.0))
    assert interaction.cancel()

    restored = selections.state(scene_id).coverage
    assert restored is not None
    assert restored.bounds == RasterBounds(4, 5, 6, 7)
    assert not edits
