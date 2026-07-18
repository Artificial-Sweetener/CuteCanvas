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

"""Tests for MaskDelegate wiring and defensive branches."""

from __future__ import annotations

from types import SimpleNamespace

from qpane.masks.delegate import MaskDelegate


def test_update_mask_from_file_rejects_missing_inputs() -> None:
    """Missing IDs or paths should return False without touching the service."""

    class _CatalogStub:
        def maskManager(self):
            return object()

    class _ServiceStub:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object, str]] = []

        def updateMaskFromPath(self, mask_id, file_path):
            self.calls.append(("update", mask_id, file_path))
            return True

    service = _ServiceStub()
    qpane = SimpleNamespace(
        catalog=lambda: _CatalogStub(),
        mask_service=service,
        featureFallbacks=lambda: SimpleNamespace(get=lambda *args, **kwargs: False),
    )
    delegate = MaskDelegate(qpane)
    assert delegate.update_mask_from_file(None, "") is False
    assert service.calls == []


def test_attach_and_detach_mask_service_wires_state() -> None:
    """Attach should wire services and detach should clear them."""

    class _WorkflowStub:
        def __init__(self) -> None:
            self.undo_slots: list[object] = []

        def on_mask_undo_stack_changed(self, mask_id):
            self.undo_slots.append(mask_id)

    class _SwapDelegateStub:
        def __init__(self) -> None:
            self.attached = False
            self.detached = False

        def on_scene_prefetcher_attached(self, _prefetcher) -> None:
            self.attached = True

        def on_scene_prefetcher_detached(self, _prefetcher) -> None:
            self.detached = True

    class _ServiceStub:
        def __init__(self) -> None:
            self.connected: list[object] = []
            self.disconnected: list[object] = []

        def connectUndoStackChanged(self, slot) -> None:
            self.connected.append(slot)

        def disconnectUndoStackChanged(self, slot) -> None:
            self.disconnected.append(slot)

        def resetStrokePipeline(self, **_kwargs) -> None:
            return None

        @property
        def controller(self):
            return "controller"

    workflow = _WorkflowStub()
    swap = _SwapDelegateStub()
    qpane = SimpleNamespace(
        mask_service=None,
        mask_controller=None,
        swapDelegate=swap,
        _masks_controller=workflow,
        refreshMaskAutosavePolicy=lambda: None,
        applyCacheSettings=lambda: None,
        _state=SimpleNamespace(cache_registry=None),
    )
    service = _ServiceStub()
    delegate = MaskDelegate(qpane)
    delegate.attachMaskService(service)
    assert qpane.mask_service is service
    assert qpane.mask_controller == "controller"
    assert swap.attached is True
    assert service.connected
    delegate.detachMaskService()
    assert qpane.mask_service is None
    assert qpane.mask_controller is None
    assert swap.detached is True
    assert service.disconnected
