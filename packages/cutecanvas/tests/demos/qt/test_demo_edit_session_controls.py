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
"""Mounted demo proof for resolving bounded editor sessions visibly."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolBar

from cutecanvas import (
    CuteCanvas,
    EditorTransformCommand,
    EditorTransformTarget,
    EditSessionKind,
    VectorShapeKind,
)
from cutecanvas_demo import ExampleOptions, ExampleWindow


def test_demo_exposes_contextual_apply_and_cancel_for_transform(
    qapp: QApplication,
) -> None:
    """A bounded transform must never trap users behind undiscoverable commands."""
    window = ExampleWindow(ExampleOptions())
    try:
        image = QImage(QSize(320, 240), QImage.Format_ARGB32)
        image.fill(QColor(35, 55, 80))
        composition_id = window.qpane.createCompositionFromImage(
            image,
            title="Bounded transform controls",
        )
        mask_id = window.qpane.createBlankMask(QSize(320, 240))
        assert mask_id is not None
        assert window.qpane.setActiveMaskID(mask_id)
        assert (
            window.qpane.addCoverageShape(
                VectorShapeKind.RECTANGLE,
                QRectF(40.0, 40.0, 120.0, 100.0),
            )
            is not None
        )
        entry = next(
            item
            for item in window.qpane.listMasksForComposition(composition_id)
            if item.mask_id == mask_id
        )
        assert entry.layer_id is not None
        window.qpane.setSelectedLayer(composition_id, entry.layer_id)
        selected = window.qpane.selectedLayer()
        assert selected is not None and selected.layer_id == entry.layer_id
        window.resize(900, 620)
        window.show()
        qapp.processEvents()

        assert window.qpane.activateEditorTransform(EditorTransformTarget.LAYER_CONTENT)
        assert window.qpane.applyEditorTransformCommand(
            EditorTransformCommand.ROTATE_RIGHT_90
        )
        qapp.processEvents()

        toolbar = _active_edit_toolbar(window)
        assert toolbar is not None and toolbar.isVisible()
        history = window.tools.editor_controls.history
        assert history.apply_action.isEnabled()
        assert history.cancel_action.isEnabled()

        history.apply_action.trigger()
        qapp.processEvents()

        assert window.qpane.activeEditSession() is None
        assert not toolbar.isVisible()
        assert window.qpane.sceneEditUndoAvailable()
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_demo_contextual_apply_resolves_shared_edge_resize(
    qapp: QApplication,
) -> None:
    """Shared-edge release must expose and execute its required settlement."""
    window = ExampleWindow(ExampleOptions())
    try:
        image = QImage(QSize(400, 300), QImage.Format_ARGB32)
        image.fill(QColor(35, 55, 80))
        window.qpane.createCompositionFromImage(
            image,
            title="Bounded shared edge controls",
        )
        first_id = window.qpane.createBlankMask(QSize(400, 300))
        assert first_id is not None
        assert window.qpane.setActiveMaskID(first_id)
        assert (
            window.qpane.addCoverageShape(
                VectorShapeKind.RECTANGLE,
                QRectF(80.0, 80.0, 80.0, 100.0),
            )
            is not None
        )
        second_id = window.qpane.createBlankMask(QSize(400, 300))
        assert second_id is not None
        assert window.qpane.setActiveMaskID(second_id)
        assert (
            window.qpane.addCoverageShape(
                VectorShapeKind.RECTANGLE,
                QRectF(160.0, 80.0, 80.0, 100.0),
            )
            is not None
        )
        window.resize(900, 620)
        window.show()
        window.tools.set_mode(CuteCanvas.CONTROL_MODE_SHARED_EDGE_RESIZE)
        window.tools.editor_controls.layer_policy.reconcile()
        qapp.processEvents()

        start = _panel_point(window.qpane, QPointF(160.0, 130.0))
        finish = _panel_point(window.qpane, QPointF(180.0, 130.0))
        QTest.mouseMove(window.qpane, start)
        QTest.mousePress(window.qpane, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(window.qpane, finish, delay=0)
        QTest.mouseRelease(window.qpane, Qt.MouseButton.LeftButton, pos=finish)
        qapp.processEvents()

        active = window.qpane.activeEditSession()
        assert active is not None
        assert active.kind is EditSessionKind.SHARED_EDGE_RESIZE
        toolbar = _active_edit_toolbar(window)
        assert toolbar is not None and toolbar.isVisible()
        history = window.tools.editor_controls.history
        assert history.apply_action.isEnabled()
        assert history.cancel_action.isEnabled()

        history.apply_action.trigger()
        qapp.processEvents()

        assert window.qpane.activeEditSession() is None
        assert not toolbar.isVisible()
        assert window.qpane.sceneEditUndoAvailable()
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def _active_edit_toolbar(window: ExampleWindow) -> QToolBar | None:
    """Return the demo's discoverable bounded-session toolbar."""
    return next(
        (
            toolbar
            for toolbar in window.findChildren(QToolBar)
            if toolbar.windowTitle() == "Active Edit"
        ),
        None,
    )


def _panel_point(canvas: CuteCanvas, scene_point: QPointF) -> QPoint:
    """Return one visible integer panel coordinate."""
    panel_point = canvas.view().scene_to_panel_point(scene_point)
    assert panel_point is not None
    return panel_point.toPoint()
