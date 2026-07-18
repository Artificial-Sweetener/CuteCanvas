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

import types
import uuid

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from qpane import QPane


def _cleanup_qpane(qpane, qapp):
    qpane.deleteLater()
    qapp.processEvents()


def _load_default_image(qpane):
    image = QImage(16, 16, QImage.Format_ARGB32)
    image.fill(Qt.white)
    image_id = uuid.uuid4()
    image_map = QPane.imageMapFromLists(
        [image],
        paths=[None],
        ids=[image_id],
    )
    qpane.setImagesByID(image_map, image_id)


class DummyCacheRegistry:
    def __init__(self):
        self.mask_controller = None

    def attach_mask_controller(self, controller):
        self.mask_controller = controller


class RecordingMaskService:
    def __init__(self):
        self.assets = types.SimpleNamespace(get_layer=lambda _mask_id: None)
        self.controller = types.SimpleNamespace(
            renders=types.SimpleNamespace(
                render_revision=lambda _mask_id: 0,
                get_by_id=lambda _mask_id, **_kwargs: None,
            ),
            edits=types.SimpleNamespace(
                advance_epoch=lambda *_args, **_kwargs: 0,
            ),
            mask_updated=types.SimpleNamespace(emit=lambda *_args: None),
            undo_stack_changed=types.SimpleNamespace(emit=lambda *_args: None),
        )
        self.connected_callback = None
        self.disconnected_callback = None
        self.refresh_calls = 0
        self.apply_calls = []

    def layer_instances_for_image(self, _image_id):
        return ()

    def scene_provider_revision(self):
        return ()

    def connectUndoStackChanged(self, callback):
        self.connected_callback = callback

    def disconnectUndoStackChanged(self, callback):
        self.disconnected_callback = callback

    def refreshAutosavePolicy(self):
        self.refresh_calls += 1

    def applyConfig(self, config):
        self.apply_calls.append(config)

    def configureStrokeDiagnostics(self, config):
        pass


def _make_recorder(flag_map, label):
    def recorder(self, *args, **kwargs):
        flag_map[label] = True

    return recorder


def test_applySettings_propagates_to_dependents(qapp, monkeypatch):
    qpane = QPane(features=())
    qpane.resize(64, 64)
    _load_default_image(qpane)
    try:
        called = {
            "catalog": False,
            "viewport": False,
            "tiles": False,
            "swap": False,
        }
        catalog = qpane.catalog().imageCatalog()
        monkeypatch.setattr(
            catalog,
            "apply_config",
            types.MethodType(_make_recorder(called, "catalog"), catalog),
        )
        qpane_view = qpane.view()
        viewport = qpane_view.viewport
        monkeypatch.setattr(
            viewport,
            "applyConfig",
            types.MethodType(_make_recorder(called, "viewport"), viewport),
        )
        tile_manager = qpane_view.tile_manager
        monkeypatch.setattr(
            tile_manager,
            "apply_config",
            types.MethodType(_make_recorder(called, "tiles"), tile_manager),
        )
        swap_delegate = qpane_view.swap_delegate
        monkeypatch.setattr(
            swap_delegate,
            "apply_config",
            types.MethodType(_make_recorder(called, "swap"), swap_delegate),
        )
        mask_service = RecordingMaskService()
        qpane.mask_service = mask_service
        qpane.applySettings(default_brush_size=qpane.settings.default_brush_size + 1)
        assert all(called.values())
        assert mask_service.apply_calls
        assert mask_service.refresh_calls == 1
    finally:
        _cleanup_qpane(qpane, qapp)


def test_attach_and_detachMaskService_wires_hooks(qapp, monkeypatch):
    qpane = QPane(features=())
    qpane.resize(32, 32)
    _load_default_image(qpane)
    qpane._state.cache_registry = DummyCacheRegistry()
    masks = qpane._masks_controller
    undo_callback = masks.on_mask_undo_stack_changed
    try:
        attached = []
        detached = []
        qpane_view = qpane.view()
        swap_delegate = qpane_view.swap_delegate
        monkeypatch.setattr(
            swap_delegate,
            "on_scene_prefetcher_attached",
            types.MethodType(
                lambda self, prefetcher: attached.append(prefetcher), swap_delegate
            ),
        )
        monkeypatch.setattr(
            swap_delegate,
            "on_scene_prefetcher_detached",
            types.MethodType(
                lambda self, prefetcher: detached.append(prefetcher),
                swap_delegate,
            ),
        )
        service = RecordingMaskService()
        qpane.attachMaskService(service)
        assert qpane.mask_service is service
        assert qpane.mask_controller is service.controller
        assert service.connected_callback == undo_callback
        assert service.refresh_calls == 1
        assert len(attached) == 1
        assert attached[0].service is service
        assert qpane._state.cache_registry.mask_controller is service.controller.renders
        qpane.detachMaskService()
        assert detached == attached
        assert service.disconnected_callback == undo_callback
        assert qpane.mask_service is None
        assert qpane.mask_controller is None
    finally:
        _cleanup_qpane(qpane, qapp)
