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

"""Mounted public proof for QPane's polished product demo."""

from __future__ import annotations

import math

from PySide6.QtCore import QSize
from PySide6.QtGui import QAction, QColor, QImage
from qpane_demo import ViewerWindow

from qpane import ClipCoordinateSpace, QPane


def test_qpane_demo_restores_catalog_viewer_and_sdk_scene(qapp) -> None:
    """Preserve viewer workflows while teaching mixed public SDK scenes."""
    window = ViewerWindow()
    window.show()
    qapp.processEvents()
    try:
        pane = window.findChild(QPane)
        assert pane is not None
        assert window.windowTitle() == "QPane Example"
        assert pane.scene() is None

        first = QImage(QSize(640, 480), QImage.Format.Format_ARGB32_Premultiplied)
        first.fill(QColor("navy"))
        second = QImage(QSize(800, 600), QImage.Format.Format_ARGB32_Premultiplied)
        second.fill(QColor("darkred"))
        window.addImage(first, label="First")
        window.addImage(second, label="Second")
        qapp.processEvents()

        assert len(window.catalog.entries) == 2
        assert window.catalog_panel.isVisible()
        assert pane.scene() is not None
        assert len(pane.scene().layers) == 1
        assert pane.calculateRenderPlan() is not None

        actual_size = next(
            action for action in window.findChildren(QAction) if action.text() == "1:1"
        )
        pane.setZoom1To1()
        native_zoom = pane.currentZoom()
        pane.applyZoom(native_zoom * 0.5)
        actual_size.trigger()
        qapp.processEvents()
        assert math.isclose(pane.currentZoom(), native_zoom)

        compare = next(
            action
            for action in window.findChildren(QAction)
            if action.text() == "Compare Next"
        )
        compare.trigger()
        qapp.processEvents()
        assert len(pane.scene().layers) == 2
        assert pane.scene().layers[1].clip is None
        plan = pane.calculateRenderPlan()
        assert plan is not None
        clip = plan.render_items[1].clip
        assert clip is not None
        assert clip.coordinate_space is ClipCoordinateSpace.NORMALIZED_SCENE
        assert clip.x == 0.5

        sdk_scene = next(
            action
            for action in window.findChildren(QAction)
            if action.text() == "Rendering SDK Scene"
        )
        sdk_scene.trigger()
        qapp.processEvents()
        assert {layer.source.kind for layer in pane.scene().layers} == {
            "image",
            "vector",
        }
        highlight = next(
            action
            for action in window.findChildren(QAction)
            if action.text() == "Highlight Top Layer"
        )
        highlight.trigger()
        qapp.processEvents()
        effects = pane.layerPresentationEffects()
        assert len(effects) == 1
        assert effects[0].layer_id == pane.scene().layers[-1].layer_id
        assert not window.grab().isNull()
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()
