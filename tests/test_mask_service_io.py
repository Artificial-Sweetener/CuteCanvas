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

"""Tests for mask service file IO and persistence."""

import uuid
from pathlib import Path
from types import MethodType, SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QObject, QPoint
from PySide6.QtGui import QImage, Qt

from qpane.catalog.image_utils import (
    numpy_to_qimage_grayscale8,
    qimage_to_numpy_grayscale8,
)
from qpane.core.config_features import MaskConfigSlice
from qpane.masks import autosave_coordination
from qpane.masks.autosave import AutosaveManager
from qpane.masks.combiner import MaskCombiner
from qpane.masks.component_adjustment import MaskComponentAdjustmentTool
from qpane.masks.layer_workflows import random_mask_color
from qpane.masks.mask import MaskAssetStore
from tests.helpers.executor_stubs import StubExecutor
from tests.helpers.mask_test_utils import drain_mask_jobs, snapshot_mask_layer
from tests.test_mask_workflows import (
    _cleanup_qpane,
    _mask_service,
    _prepare_qpane_with_mask_feature,
    _queue_pending_stroke,
)

pytest_plugins = ("tests.test_mask_workflows",)


def test_mask_service_load_mask_records_success(qpane_with_mask, tmp_path):
    qpane, _mask_manager, image_id = qpane_with_mask
    service = _mask_service(qpane)
    service._status_messages.clear()
    grayscale = QImage(8, 8, QImage.Format_Grayscale8)
    grayscale.fill(Qt.white)
    mask_path = tmp_path / "mask.png"
    assert grayscale.save(str(mask_path))
    mask_id = service.loadMaskFromPath(str(mask_path))
    assert mask_id is not None
    assert mask_id in service.mask_ids_for_image(image_id)
    label, message = service._status_messages[-1]
    assert label == "Mask"
    assert str(mask_path) in message


def test_mask_service_load_mask_requires_image(qpane_with_mask, tmp_path):
    qpane, _, _ = qpane_with_mask
    service = _mask_service(qpane)
    service._status_messages.clear()
    qpane.original_image = QImage()
    grayscale = QImage(8, 8, QImage.Format_Grayscale8)
    grayscale.fill(Qt.white)
    mask_path = tmp_path / "mask_missing.png"
    assert grayscale.save(str(mask_path))
    result = service.loadMaskFromPath(str(mask_path))
    assert result is None
    label, message = service._status_messages[-1]
    assert label == "Mask Error"
    assert message == "Cannot load a mask before an image is set."


def test_mask_service_update_mask_missing_layer(qpane_with_mask, tmp_path):
    qpane, _, _ = qpane_with_mask
    service = _mask_service(qpane)
    service._status_messages.clear()
    grayscale = QImage(8, 8, QImage.Format_Grayscale8)
    grayscale.fill(Qt.white)
    mask_path = tmp_path / "update_mask.png"
    assert grayscale.save(str(mask_path))
    unknown_id = uuid.uuid4()
    result = service.updateMaskFromPath(unknown_id, str(mask_path))
    assert result is False
    label, message = service._status_messages[-1]
    assert label == "Mask Error"
    assert str(unknown_id) in message


def test_random_mask_color_is_deterministic():
    hues = [random_mask_color(i).hue() for i in range(5)]
    assert hues[:3] == [0, 221, 84]
    assert len(set(hues[:3])) == 3


def test_createBlankMask_assigns_sequential_colors(qpane_with_mask):
    qpane, _mask_manager, _ = qpane_with_mask
    service = _mask_service(qpane)
    base_image = qpane.catalog().currentImage()
    assert base_image is not None
    first_id = service.createBlankMask(base_image.size())
    second_id = service.createBlankMask(base_image.size())
    assert first_id is not None and second_id is not None
    first_instance = service.layer_instance_for_mask(first_id)
    second_instance = service.layer_instance_for_mask(second_id)
    assert first_instance is not None and second_instance is not None
    assert first_instance.tint != second_instance.tint
    assert first_instance.tint.hue() == random_mask_color(0).hue()
    assert second_instance.tint.hue() == random_mask_color(1).hue()


def test_combine_with_numpy_mask_resizes_mismatched_shapes():
    manager = MaskAssetStore()
    base_image = QImage(8, 8, QImage.Format_Grayscale8)
    base_image.fill(Qt.black)
    mask_id = manager.create_mask(base_image)
    small_mask = np.zeros((4, 2), dtype=np.uint8)
    small_mask[:, 0] = 255
    result = MaskCombiner(manager).combine(mask_id, small_mask)
    assert result is not None
    manager.commit_mask_image(mask_id, result)
    combined = manager.get_mask_image_as_numpy(mask_id)
    assert combined.shape == (8, 8)
    assert np.all(combined[:, :4] == 255)


def test_combine_resize_preserves_nearest_sampling_contract():
    manager = MaskAssetStore()
    base_image = QImage(5, 4, QImage.Format_Grayscale8)
    base_image.fill(Qt.black)
    mask_id = manager.create_mask(base_image)
    source = np.arange(6, dtype=np.uint8).reshape(2, 3)
    result = MaskCombiner(manager).combine(mask_id, source)
    assert result is not None
    manager.commit_mask_image(mask_id, result)
    assert np.array_equal(
        manager.get_mask_image_as_numpy(mask_id),
        np.array(
            [
                [0, 0, 1, 1, 2],
                [0, 0, 1, 1, 2],
                [3, 3, 4, 4, 5],
                [3, 3, 4, 4, 5],
            ],
            dtype=np.uint8,
        ),
    )


def test_combine_with_numpy_mask_coerces_bool_arrays():
    manager = MaskAssetStore()
    base_image = QImage(4, 4, QImage.Format_Grayscale8)
    base_image.fill(Qt.black)
    mask_id = manager.create_mask(base_image)
    bool_mask = np.zeros((4, 4), dtype=bool)
    bool_mask[1, 2] = True
    result = MaskCombiner(manager).combine(mask_id, bool_mask)
    assert result is not None
    manager.commit_mask_image(mask_id, result)
    stored = manager.get_mask_image_as_numpy(mask_id)
    assert stored is not None
    assert stored.dtype == np.uint8
    assert stored[1, 2] == 255
    assert np.count_nonzero(stored) == 1


def test_combine_with_numpy_mask_erase_clears_null_layer():
    manager = MaskAssetStore()
    base_image = QImage(4, 4, QImage.Format_Grayscale8)
    base_image.fill(Qt.black)
    mask_id = manager.create_mask(base_image)
    manager.set_mask_image(mask_id, QImage())
    layer = manager.get_layer(mask_id)
    assert layer is not None
    assert layer.mask_image.isNull()
    erase_mask = np.ones((4, 4), dtype=np.uint8) * 255
    result = MaskCombiner(manager).combine(mask_id, erase_mask, erase_mode=True)
    assert result is not None
    manager.commit_mask_image(mask_id, result)
    updated_layer = manager.get_layer(mask_id)
    assert updated_layer is not None
    assert not updated_layer.mask_image.isNull()
    stored = manager.get_mask_image_as_numpy(mask_id)
    assert stored is not None
    assert stored.shape == (4, 4)
    assert np.count_nonzero(stored) == 0


def test_adjust_component_out_of_bounds_guard():
    manager = MaskAssetStore()
    base_image = QImage(8, 8, QImage.Format_Grayscale8)
    base_image.fill(Qt.black)
    mask_id = manager.create_mask(base_image)
    layer = manager.get_layer(mask_id)
    assert layer is not None
    layer.surface.fill(Qt.white)
    baseline_state = manager.get_undo_state(mask_id)
    assert baseline_state is not None
    result = MaskComponentAdjustmentTool(manager).adjusted_image(
        mask_id, QPoint(20, 20), grow=True
    )
    assert result is None
    assert manager.get_undo_state(mask_id) == baseline_state
    assert layer.mask_image.pixelColor(0, 0).value() == 255


def test_adjust_component_uses_eight_connectivity_and_cross_dilation():
    manager = MaskAssetStore()
    base_image = QImage(7, 7, QImage.Format_Grayscale8)
    base_image.fill(Qt.black)
    mask_id = manager.create_mask(base_image)
    source = np.zeros((7, 7), dtype=np.uint8)
    source[2, 2] = 255
    source[3, 3] = 255
    source[5, 5] = 255
    manager.set_mask_image(mask_id, numpy_to_qimage_grayscale8(source))
    result = MaskComponentAdjustmentTool(manager).adjusted_image(
        mask_id, QPoint(2, 2), grow=True
    )
    assert result is not None
    adjusted = qimage_to_numpy_grayscale8(result)
    expected = source.copy()
    expected[1:4, 2] = 255
    expected[2, 1:4] = 255
    expected[2:5, 3] = 255
    expected[3, 2:5] = 255
    assert np.array_equal(adjusted, expected)


def test_adjust_component_shrinks_only_selected_component():
    manager = MaskAssetStore()
    base_image = QImage(8, 6, QImage.Format_Grayscale8)
    base_image.fill(Qt.black)
    mask_id = manager.create_mask(base_image)
    source = np.zeros((6, 8), dtype=np.uint8)
    source[1:4, 1:4] = 255
    source[1:4, 5:8] = 255
    manager.set_mask_image(mask_id, numpy_to_qimage_grayscale8(source))
    result = MaskComponentAdjustmentTool(manager).adjusted_image(
        mask_id, QPoint(2, 2), grow=False
    )
    assert result is not None
    adjusted = qimage_to_numpy_grayscale8(result)
    expected = np.zeros_like(source)
    expected[2, 2] = 255
    expected[1:4, 5:8] = 255
    assert np.array_equal(adjusted, expected)


def test_async_strokes_sync_undo_and_autosave(monkeypatch, qapp):
    """Undo/redo stacks and autosave notifications stay consistent with worker commits."""
    executor = StubExecutor(auto_finish=False)
    qpane, image = _prepare_qpane_with_mask_feature(executor=executor)
    service = _mask_service(qpane)
    assert service is not None
    mask_id = service.createBlankMask(image.size())
    assert mask_id is not None
    assert qpane.setActiveMaskID(mask_id)
    layer = service.assets.get_layer(mask_id)
    assert layer is not None
    layer.surface.fill(0)
    qpane.interaction.brush_size = 5
    autosave_manager = qpane.autosaveManager()
    assert autosave_manager is not None
    autosave_calls: list[str] = []

    def _tracking_schedule(self, target_mask_id, dirty_rect=None):
        autosave_calls.append(str(target_mask_id))

    autosave_manager.scheduleSave = MethodType(_tracking_schedule, autosave_manager)
    try:
        _queue_pending_stroke(qpane, QPoint(4, 4))
        pending, tokens = drain_mask_jobs(qpane, executor=executor)
        assert not pending and not tokens
        state = service.assets.get_undo_state(mask_id)
        assert state is not None and state.undo_depth == 1
        assert autosave_calls and autosave_calls[-1] == str(mask_id)
        first_autosave_count = len(autosave_calls)
        assert service.assets.undo_mask(mask_id) is not None
        undone_snapshot = snapshot_mask_layer(layer)
        assert not np.any(undone_snapshot)
        _queue_pending_stroke(qpane, QPoint(9, 9))
        assert service.assets.redo_mask(mask_id) is not None
        pending_after_redo = service.strokeDebugSnapshot().pending_jobs
        assert mask_id in pending_after_redo
        drain_mask_jobs(qpane, executor=executor)
        final_snapshot = snapshot_mask_layer(layer)
        assert final_snapshot[4, 4] == 255
        assert final_snapshot[9, 9] == 255
        state = service.assets.get_undo_state(mask_id)
        assert state is not None and state.undo_depth == 2
        assert len(autosave_calls) >= first_autosave_count + 1
    finally:
        _cleanup_qpane(qpane, qapp)


class _DummySignal:
    """Minimal signal stand-in that records connected callables."""

    def __init__(self) -> None:
        self._slots: list = []

    def connect(self, slot) -> None:
        self._slots.append(slot)

    def disconnect(self, slot) -> None:
        try:
            self._slots.remove(slot)
        except ValueError as exc:
            raise TypeError("slot not connected") from exc

    def emit(self, *args, **kwargs) -> None:
        for slot in list(self._slots):
            slot(*args, **kwargs)


@pytest.mark.usefixtures("qapp")
def test_mask_autosave_coordinator_uses_shared_executor(monkeypatch) -> None:
    """Mask autosave coordination should wire the provided executor into AutosaveManager."""
    executor = StubExecutor()
    mask_manager = SimpleNamespace(get_layer=lambda _mask_id: None)
    mask_controller = SimpleNamespace(
        mask_updated=_DummySignal(),
        active_mask_properties_changed=_DummySignal(),
        get_active_mask_id=lambda: None,
    )

    class _QPane(QObject):
        def __init__(self) -> None:
            super().__init__()
            self.settings = MaskConfigSlice(mask_autosave_enabled=True)
            self.currentImagePath = Path("qpane-image.png")
            self.mask_service = object()
            self._autosave_manager = None
            self.original_image = QImage(4, 4, QImage.Format_ARGB32)
            self.original_image.fill(Qt.white)
            self._workflow = SimpleNamespace(
                on_mask_saved=lambda *args, **kwargs: None,
                on_mask_undo_stack_changed=lambda *args, **kwargs: None,
            )
            self._masks_controller = self._workflow

        def attachAutosaveManager(self, manager) -> None:
            self._autosave_manager = manager

        def detachAutosaveManager(self) -> None:
            self._autosave_manager = None

        def autosaveManager(self):
            return self._autosave_manager

    qpane = _QPane()
    monkeypatch.setattr(
        autosave_coordination, "should_enable_mask_autosave", lambda _qpane: True
    )
    coordinator = autosave_coordination.MaskAutosaveCoordinator(
        qpane=qpane,
        mask_assets=mask_manager,
        mask_controller=mask_controller,
        executor=executor,
        publish_status=lambda *_args, **_kwargs: None,
    )
    coordinator.refresh()
    assert isinstance(qpane.autosaveManager(), AutosaveManager)
    assert qpane.autosaveManager()._executor is executor
    qpane.autosaveManager().shutdown()
    coordinator._disconnect(force=True)
