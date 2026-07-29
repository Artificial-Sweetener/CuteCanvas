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

"""Mounted host workflows for generic layers and retained coverage authoring."""

from __future__ import annotations

from cutecanvas import (
    CoverageCoordinateSpace,
    CuteCanvas,
    PixelSelectionMode,
)
from PySide6.QtCore import QPointF, QRect, QRectF, QSize
from PySide6.QtGui import QColor, QImage, QTransform
from PySide6.QtTest import QSignalSpy

from tests.harness.timing import interaction_clock

_HOST_COMMAND_BUDGET_MS = 4.0


def _opaque_image(width: int = 40, height: int = 20) -> QImage:
    """Return one opaque editable image."""
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0xFF4FA3D1)
    return image


def test_layer_handle_visibility_is_generic_and_chronological(qapp) -> None:
    """A host can hide any layer and undo or redo that presentation edit."""
    canvas = CuteCanvas(features=())
    try:
        document = canvas.editor.compositions.create(QRectF(0.0, 0.0, 200.0, 100.0))
        layer_id = canvas.addEditableRasterLayer(_opaque_image(), label="Subject")
        layer = document.layer(layer_id)
        assert layer is not None
        assert layer.state.visible

        changed = QSignalSpy(canvas.sceneChanged)
        assert layer.set_visible(False)
        assert not layer.state.visible
        assert changed.count() == 1
        assert canvas.undoSceneEdit()
        assert layer.state.visible
        assert canvas.redoSceneEdit()
        assert not layer.state.visible
    finally:
        canvas.deleteLater()
        qapp.processEvents()


def test_layer_handle_translation_and_centering_preserve_affine_geometry(qapp) -> None:
    """Host conveniences retain scale and rotation while changing translation."""
    canvas = CuteCanvas(features=())
    try:
        document = canvas.editor.compositions.create(QRectF(10.0, 20.0, 200.0, 100.0))
        layer_id = canvas.addEditableRasterLayer(_opaque_image(), label="Subject")
        layer = document.layer(layer_id)
        assert layer is not None
        original = QTransform()
        original.rotate(30.0)
        original.scale(1.5, 0.75)
        assert layer.set_transform(original)

        assert layer.translate(QPointF(17.5, -3.25))
        translated = layer.state.transform
        assert translated.m11() == original.m11()
        assert translated.m12() == original.m12()
        assert translated.m21() == original.m21()
        assert translated.m22() == original.m22()

        assert layer.center()
        scene = canvas.currentScene()
        local = canvas.layerLocalBounds(scene.scene_id, layer_id)
        assert local is not None
        centered = layer.state.transform.mapRect(local).center()
        assert abs(centered.x() - scene.bounds.center().x()) < 1e-9
        assert abs(centered.y() - scene.bounds.center().y()) < 1e-9
    finally:
        canvas.deleteLater()
        qapp.processEvents()


def test_retained_shape_authoring_can_split_two_masks_exactly(qapp) -> None:
    """Two host-authored rectangles can partition an image-aligned mask canvas."""
    canvas = CuteCanvas(features=("mask",))
    try:
        canvas.editor.compositions.create(QRectF(0.0, 0.0, 64.0, 32.0))
        left_id = canvas.createBlankMask(QSize(64, 32))
        assert left_id is not None
        assert canvas.setActiveMaskID(left_id)
        left_item = canvas.editor.coverage.rectangle(
            QRectF(0.0, 0.0, 0.5, 1.0),
            PixelSelectionMode.ADD,
            coordinate_space=CoverageCoordinateSpace.NORMALIZED_TARGET,
        )
        assert left_item is not None
        left = canvas.getActiveMaskImage()
        assert left is not None
        assert left.pixelColor(31, 12).value() == 255
        assert left.pixelColor(32, 12).value() == 0

        right_id = canvas.createBlankMask(QSize(64, 32))
        assert right_id is not None
        assert canvas.setActiveMaskID(right_id)
        right_item = canvas.editor.coverage.rectangle(
            QRectF(0.5, 0.0, 0.5, 1.0),
            PixelSelectionMode.ADD,
            coordinate_space=CoverageCoordinateSpace.NORMALIZED_TARGET,
        )
        assert right_item is not None
        right = canvas.getActiveMaskImage()
        assert right is not None
        assert right.pixelColor(31, 12).value() == 0
        assert right.pixelColor(32, 12).value() == 255
    finally:
        canvas.deleteLater()
        qapp.processEvents()


def test_normalized_mask_coordinates_do_not_shrink_to_existing_content(qapp) -> None:
    """Percentage geometry must remain anchored to stable raster storage bounds."""
    canvas = CuteCanvas(features=("mask",))
    try:
        canvas.editor.compositions.create(QRectF(0.0, 0.0, 100.0, 40.0))
        mask_id = canvas.createBlankMask(QSize(100, 40))
        assert mask_id is not None and canvas.setActiveMaskID(mask_id)
        assert canvas.editor.coverage.rectangle(
            QRectF(0.0, 0.0, 0.5, 1.0),
            coordinate_space=CoverageCoordinateSpace.NORMALIZED_TARGET,
        )
        assert canvas.editor.coverage.rectangle(
            QRectF(0.5, 0.0, 0.5, 1.0),
            coordinate_space=CoverageCoordinateSpace.NORMALIZED_TARGET,
        )

        mask = canvas.getActiveMaskImage()
        assert mask is not None
        assert mask.pixelColor(0, 20).value() == 255
        assert mask.pixelColor(99, 20).value() == 255
    finally:
        canvas.deleteLater()
        qapp.processEvents()


def test_export_addressed_mask_preserves_inactive_editor_state(qapp) -> None:
    """Addressed mask export must not activate another document or mask."""
    canvas = CuteCanvas(features=("mask",))
    try:
        first = canvas.editor.compositions.create(QRectF(0.0, 0.0, 64.0, 32.0))
        first_mask_id = canvas.createBlankMask(QSize(64, 32))
        assert first_mask_id is not None
        assert canvas.setActiveMaskID(first_mask_id)
        assert canvas.editor.coverage.rectangle(
            QRectF(0.0, 0.0, 0.5, 1.0),
            PixelSelectionMode.ADD,
            coordinate_space=CoverageCoordinateSpace.NORMALIZED_TARGET,
        )

        second = canvas.editor.compositions.create(QRectF(0.0, 0.0, 64.0, 32.0))
        second_mask_id = canvas.createBlankMask(QSize(64, 32))
        assert second_mask_id is not None
        assert canvas.setActiveMaskID(second_mask_id)
        assert canvas.currentCompositionID() == second.id
        assert canvas.activeMaskID() == second_mask_id
        scene_changes = QSignalSpy(canvas.sceneChanged)

        exported = canvas.exportMaskImage(
            first_mask_id,
            composition_id=first.id,
        )

        assert exported is not None
        assert exported.pixelColor(31, 12).value() == 255
        assert exported.pixelColor(32, 12).value() == 0
        assert canvas.currentCompositionID() == second.id
        assert canvas.activeMaskID() == second_mask_id
        assert scene_changes.count() == 0
    finally:
        canvas.deleteLater()
        qapp.processEvents()


def test_replacing_addressed_mask_pixels_retains_identity_and_activation(qapp) -> None:
    """Host replacement keeps the resource identity and current edit destination."""
    canvas = CuteCanvas(features=("mask",))
    try:
        composition = canvas.editor.compositions.create(QRectF(0.0, 0.0, 32.0, 24.0))
        target_mask_id = canvas.createBlankMask(QSize(32, 24))
        other_mask_id = canvas.createBlankMask(QSize(32, 24))
        assert target_mask_id is not None and other_mask_id is not None
        assert canvas.setActiveMaskID(other_mask_id)
        replacement = QImage(32, 24, QImage.Format.Format_Grayscale8)
        replacement.fill(91)

        assert canvas.replaceMaskImage(target_mask_id, replacement)

        assert canvas.activeMaskID() == other_mask_id
        assert target_mask_id in canvas.maskIDsForComposition(composition.id)
        exported = canvas.exportMaskImage(
            target_mask_id,
            composition_id=composition.id,
        )
        assert exported is not None
        assert exported.pixelColor(8, 11).value() == 91
    finally:
        canvas.deleteLater()
        qapp.processEvents()


def test_arbitrary_soft_coverage_commits_without_mutating_pixel_selection(qapp) -> None:
    """A host can add bounded grayscale coverage directly to an active mask."""
    canvas = CuteCanvas(features=("mask",))
    try:
        canvas.editor.compositions.create(QRectF(0.0, 0.0, 32.0, 24.0))
        mask_id = canvas.createBlankMask(QSize(32, 24))
        assert mask_id is not None
        assert canvas.setActiveMaskID(mask_id)
        coverage = QImage(5, 3, QImage.Format.Format_Grayscale8)
        coverage.fill(129)

        item_id = canvas.addCoverageImage(
            coverage,
            QRect(7, 9, 5, 3),
            PixelSelectionMode.ADD,
        )

        assert item_id is not None
        assert canvas.pixelSelectionState() is not None
        assert not canvas.pixelSelectionState().has_selection
        mask = canvas.getActiveMaskImage()
        assert mask is not None
        assert 127 <= mask.pixelColor(7, 9).value() <= 130
        assert mask.pixelColor(6, 9).value() == 0
    finally:
        canvas.deleteLater()
        qapp.processEvents()


def test_retained_coverage_facade_targets_pixel_selection_and_undo(qapp) -> None:
    """The same authoring facade should target selection without mask logic."""
    canvas = CuteCanvas(features=())
    try:
        canvas.editor.compositions.create(QRectF(10.0, 20.0, 80.0, 40.0))
        assert canvas.setPixelSelectionPaintTarget()
        assert canvas.editor.coverage.ellipse(
            QRectF(0.25, 0.25, 0.5, 0.5),
            PixelSelectionMode.REPLACE,
            coordinate_space=CoverageCoordinateSpace.NORMALIZED_TARGET,
        )
        selection = canvas.pixelSelectionState()
        assert selection is not None and selection.has_selection
        assert selection.bounds == QRect(30, 30, 40, 20)
        assert canvas.undoSceneEdit()
        restored = canvas.pixelSelectionState()
        assert restored is not None and not restored.has_selection
        assert canvas.redoSceneEdit()
        assert canvas.pixelSelectionState().has_selection
    finally:
        canvas.deleteLater()
        qapp.processEvents()


def test_host_authoring_commands_remain_responsive_under_storms(qapp) -> None:
    """Visibility, alignment, and retained geometry must survive rapid host use."""
    canvas = CuteCanvas(features=("mask",))
    try:
        document = canvas.editor.compositions.create(QRectF(0.0, 0.0, 4096.0, 4096.0))
        layer_id = canvas.addEditableRasterLayer(_opaque_image(256, 256))
        layer = document.layer(layer_id)
        assert layer is not None

        started = interaction_clock()
        for index in range(200):
            assert layer.set_visible(index % 2 == 1)
        visibility_ms = (interaction_clock() - started) * 1000.0 / 200.0

        started = interaction_clock()
        for _ in range(100):
            assert layer.translate(QPointF(3.0, -2.0))
            assert layer.center()
        alignment_ms = (interaction_clock() - started) * 1000.0 / 200.0

        mask_id = canvas.createBlankMask(QSize(4096, 4096))
        assert mask_id is not None and canvas.setActiveMaskID(mask_id)
        started = interaction_clock()
        for index in range(128):
            left = float((index * 31) % 3900)
            top = float((index * 47) % 3900)
            assert canvas.editor.coverage.rectangle(QRectF(left, top, 128.0, 96.0))
        coverage_ms = (interaction_clock() - started) * 1000.0 / 128.0

        assert visibility_ms < _HOST_COMMAND_BUDGET_MS
        assert alignment_ms < _HOST_COMMAND_BUDGET_MS
        assert coverage_ms < _HOST_COMMAND_BUDGET_MS
        qapp.processEvents()
        assert len(canvas.currentScene().layers) == 2
    finally:
        canvas.deleteLater()
        qapp.processEvents()


def test_layer_handle_highlight_is_transient_and_renderer_owned(qapp) -> None:
    """Editor highlights never mutate document state or chronological history."""
    canvas = CuteCanvas(features=())
    try:
        document = canvas.editor.compositions.create(QRectF(0.0, 0.0, 200.0, 100.0))
        layer_id = canvas.addEditableRasterLayer(_opaque_image(), label="Subject")
        layer = document.layer(layer_id)
        assert layer is not None
        before = layer.state
        undo_before = canvas.sceneEditUndoAvailable()

        effect = canvas.editor.effects.highlight(
            layer,
            color=QColor(80, 160, 230),
            width=2.0,
        )

        assert effect.state.layer_id == layer_id
        assert layer.state == before
        assert canvas.sceneEditUndoAvailable() == undo_before
        plan = canvas.view().calculateRenderPlan()
        assert plan is not None
        assert tuple(value.effect_id for value in plan.presentation_effects) == (
            effect.id,
        )
        assert effect.remove()
        assert canvas.layerPresentationEffects() == ()
    finally:
        canvas.deleteLater()
        qapp.processEvents()
