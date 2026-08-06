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
"""Mounted public proof for CuteCanvas's polished product demo."""

from __future__ import annotations

from cutecanvas import CuteCanvas
from cutecanvas_demo import ExampleOptions, ExampleWindow


def test_cutecanvas_demo_mounts_an_editable_layered_document(qapp) -> None:
    """The editor demo opens with a usable raster, paint, and vector stack."""
    window = ExampleWindow(ExampleOptions())
    window.show()
    qapp.processEvents()
    try:
        canvas = window.findChild(CuteCanvas)
        assert canvas is not None
        scene = canvas.currentScene()
        assert scene is not None
        assert len(scene.layers) == 3
        assert [layer.label for layer in scene.layers[1:]] == [
            "Paint",
            "Welcome shapes",
        ]
        selected = canvas.selectedLayer()
        assert selected is not None
        assert selected.layer_id == scene.layers[-1].layer_id
        assert not window.grab().isNull()
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()
