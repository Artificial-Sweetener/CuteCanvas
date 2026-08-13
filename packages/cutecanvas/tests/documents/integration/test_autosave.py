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

"""Verify mask autosave scheduling, retry, atomic output, and teardown."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QObject, QSize
from PySide6.QtGui import QImage, Qt

from cutecanvas.core.config_features import MaskConfigSlice
from cutecanvas.masks.autosave import AutosaveManager
from cutecanvas.masks.install import should_enable_mask_autosave
from cutecanvas.runtime.latest_requests import DocumentLatestRequestRegistry
from cutecanvas_test_support.execution_backend import (
    ControllableExecutionBackend,
    RejectingExecutionBackend,
)
from qpane.sdk.execution import ExecutionRuntime, InlineDispatcher


class DummyTimer:
    """Record one debounce start without waiting for wall time."""

    def __init__(self) -> None:
        """Create an idle timer stub."""
        self.started_interval: int | None = None

    def start(self, interval: int) -> None:
        """Record the requested interval."""
        self.started_interval = interval

    def isActive(self) -> bool:
        """Return whether the stub has been started."""
        return self.started_interval is not None

    def remainingTime(self) -> int:
        """Return the retained interval."""
        return -1 if self.started_interval is None else self.started_interval

    def stop(self) -> None:
        """Reset the retained timer state."""
        self.started_interval = None


def _build_manager(
    settings: MaskConfigSlice,
    *,
    image_path: Path | None = None,
    backend: ControllableExecutionBackend | None = None,
    payload: object | None = None,
) -> tuple[
    AutosaveManager,
    QObject,
    ExecutionRuntime,
    ControllableExecutionBackend,
]:
    """Create one manager over a public deterministic execution backend."""
    resolved_backend = backend or ControllableExecutionBackend()
    runtime = ExecutionRuntime(resolved_backend)
    scope = runtime.open_scope(
        owner_id="autosave-test",
        dispatcher=InlineDispatcher(),
    )
    parent = QObject()
    image = QImage(4, 4, QImage.Format_ARGB32)
    image.fill(Qt.GlobalColor.white)
    manager = AutosaveManager(
        snapshot_provider=lambda _mask_id: image if payload is None else payload,
        settings=settings,
        get_current_image_path=lambda: image_path or Path("example.png"),
        execution_scope=scope,
        latest_requests=DocumentLatestRequestRegistry(),
        parent=parent,
    )
    manager._autosave_timer = DummyTimer()
    return manager, parent, runtime, resolved_backend


def _settings(tmp_path: Path, *, creation: bool = False) -> MaskConfigSlice:
    """Return enabled autosave settings rooted in one temporary directory."""
    return MaskConfigSlice(
        mask_autosave_enabled=True,
        mask_autosave_on_creation=creation,
        mask_autosave_path_template=str(tmp_path / "{image_name}-{mask_id}.png"),
    )


def test_schedule_save_obeys_enabled_policy(tmp_path, qapp) -> None:
    """Disabled managers ignore dirtiness while enabled managers debounce it."""
    disabled = MaskConfigSlice(mask_autosave_enabled=False)
    manager, _parent, runtime, _backend = _build_manager(disabled)
    manager.scheduleSave("mask-1")
    assert manager.pending_mask_count() == 0
    assert manager._autosave_timer.started_interval is None
    runtime.shutdown()

    enabled = _settings(tmp_path)
    manager, _parent, runtime, _backend = _build_manager(enabled)
    manager.scheduleSave("mask-2")
    assert manager.pending_mask_count() == 1
    assert manager._autosave_timer.started_interval == enabled.mask_autosave_debounce_ms
    runtime.shutdown()


def test_document_autosave_replaces_work_from_another_view(
    tmp_path: Path,
    qapp,
) -> None:
    """One document freshness owner must prevent stale cross-view persistence."""
    backend = ControllableExecutionBackend()
    runtime = ExecutionRuntime(backend)
    document_scope = runtime.open_scope(
        owner_id="autosave-document",
        dispatcher=InlineDispatcher(),
    )
    latest_requests = DocumentLatestRequestRegistry()
    settings = _settings(tmp_path, creation=True)
    target = tmp_path / "shared.png"
    actual = QImage(4, 4, QImage.Format_ARGB32)
    actual.fill(Qt.GlobalColor.white)
    first_parent = QObject()
    second_parent = QObject()
    first = AutosaveManager(
        snapshot_provider=lambda _mask_id: QImage(4, 4, QImage.Format_ARGB32),
        settings=settings,
        get_current_image_path=lambda: Path("example.png"),
        execution_scope=document_scope,
        latest_requests=latest_requests,
        parent=first_parent,
    )
    second = AutosaveManager(
        snapshot_provider=lambda _mask_id: actual,
        settings=settings,
        get_current_image_path=lambda: Path("example.png"),
        execution_scope=document_scope,
        latest_requests=latest_requests,
        parent=second_parent,
    )
    try:
        first.saveBlankMask("shared", QSize(4, 4))
        assert backend.pending_jobs()[0].operation == (
            "editor.mask.autosave.encode_blank"
        )

        second.saveMaskToPath("shared", target)

        assert len(backend.cancelled) == 1
        assert len(backend.pending_jobs()) == 1
        assert backend.pending_jobs()[0].operation == "editor.mask.autosave.save"
        assert first.activeSaveCount() == 0
        backend.run_all()
        qapp.processEvents()

        saved = QImage(str(target))
        assert not saved.isNull()
        assert saved.pixelColor(0, 0) == actual.pixelColor(0, 0)
        assert second.activeSaveCount() == 0
    finally:
        first.shutdown()
        second.shutdown()
        latest_requests.close()
        document_scope.close(reason="test complete")
        runtime.shutdown()


def test_perform_save_uses_template_and_atomic_background_write(
    tmp_path,
    qapp,
) -> None:
    """A dirty mask resolves its template and publishes only complete PNG data."""
    manager, _parent, runtime, backend = _build_manager(
        _settings(tmp_path),
        image_path=tmp_path / "source.png",
    )
    completed: list[tuple[str, str]] = []
    manager.saveCompleted.connect(lambda *args: completed.append(args))
    manager.scheduleSave("mask-42")
    manager.performSave()
    assert backend.pending_jobs()[0].operation == "editor.mask.autosave.save"
    backend.run_all()
    destination = tmp_path / "source-mask-42.png"
    assert completed == [("mask-42", str(destination))]
    assert destination.exists()
    assert QImage(str(destination)).isNull() is False
    assert not list(tmp_path.glob("*.tmp"))
    runtime.shutdown()


def test_blank_mask_encodes_then_saves_as_two_typed_operations(
    tmp_path,
    qapp,
) -> None:
    """Creation autosave keeps encoding and persistence independently observable."""
    manager, _parent, runtime, backend = _build_manager(
        _settings(tmp_path, creation=True)
    )
    manager.saveBlankMask("blank", QSize(7, 5))
    assert [job.operation for job in backend.pending_jobs()] == [
        "editor.mask.autosave.encode_blank"
    ]
    backend.run_next()
    assert [job.operation for job in backend.pending_jobs()] == [
        "editor.mask.autosave.save"
    ]
    backend.run_next()
    result = QImage(str(tmp_path / "example-blank.png"))
    assert result.size() == QSize(7, 5)
    assert result.pixelColor(0, 0).alpha() == 0
    runtime.shutdown()


def test_blank_mask_skips_existing_destination(tmp_path, qapp) -> None:
    """Creation autosave never overwrites a pre-existing mask."""
    destination = tmp_path / "example-existing.png"
    destination.write_bytes(b"preserve")
    manager, _parent, runtime, backend = _build_manager(
        _settings(tmp_path, creation=True)
    )
    manager.saveBlankMask("existing", QSize(8, 8))
    assert backend.pending_count == 0
    assert destination.read_bytes() == b"preserve"
    runtime.shutdown()


def test_failed_encode_emits_error_without_partial_file(
    monkeypatch,
    tmp_path,
    qapp,
) -> None:
    """Encoding failures settle once and leave no destination artifact."""
    manager, _parent, runtime, backend = _build_manager(_settings(tmp_path))
    failures: list[tuple[str, str, Exception]] = []
    manager.saveFailed.connect(lambda *args: failures.append(args))

    def _fail(*_args, **_kwargs):
        """Reject the detached product deterministically."""
        raise RuntimeError("encode failed")

    monkeypatch.setattr(
        "cutecanvas.masks.autosave.save_mask_payload",
        _fail,
    )
    destination = tmp_path / "broken.png"
    manager.saveMaskToPath("broken", destination)
    backend.run_all()
    assert len(failures) == 1
    assert failures[0][:2] == ("broken", str(destination))
    assert not destination.exists()
    runtime.shutdown()


def test_cancel_pending_mask_uses_handle_and_suppresses_publication(
    tmp_path,
    qapp,
) -> None:
    """Cancellation removes pending work without worker-side fallback state."""
    manager, _parent, runtime, backend = _build_manager(_settings(tmp_path))
    completed: list[tuple[str, str]] = []
    manager.saveCompleted.connect(lambda *args: completed.append(args))
    manager.saveMaskToPath("cancel", tmp_path / "cancel.png")
    assert backend.pending_count == 1
    manager.cancelPendingMask("cancel")
    assert backend.pending_count == 0
    assert len(backend.cancelled) == 1
    assert manager.activeSaveCount() == 0
    assert completed == []
    runtime.shutdown()


def test_rejected_save_retries_with_latest_coalesced_payload(
    tmp_path,
    qapp,
) -> None:
    """Structured saturation retains only the latest payload for one mask."""
    backend = RejectingExecutionBackend(
        rejection_counts={"editor.mask.autosave.save": 1}
    )
    manager, _parent, runtime, _backend = _build_manager(
        _settings(tmp_path),
        backend=backend,
    )
    throttled: list[tuple[str, str, int]] = []
    manager.saveThrottled.connect(lambda *args: throttled.append(args))
    first = QImage(2, 2, QImage.Format_ARGB32)
    first.fill(Qt.GlobalColor.black)
    latest = QImage(3, 3, QImage.Format_ARGB32)
    latest.fill(Qt.GlobalColor.white)
    manager._snapshot_provider = lambda _mask_id: first
    destination = tmp_path / "retry.png"
    manager.saveMaskToPath("retry", destination)
    manager._snapshot_provider = lambda _mask_id: latest
    manager.saveMaskToPath("retry", destination)
    deadline = time.monotonic() + 1.5
    while backend.pending_count == 0 and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    assert throttled == [("retry", str(destination), 1)]
    assert backend.pending_count == 1
    backend.run_all()
    assert QImage(str(destination)).size() == QSize(3, 3)
    assert manager.retry_snapshot().categories["editor.mask.autosave"].active == 0
    runtime.shutdown()


def test_active_count_includes_blank_and_save_operations(tmp_path, qapp) -> None:
    """Diagnostics count every accepted task owned by autosave."""
    manager, _parent, runtime, backend = _build_manager(
        _settings(tmp_path, creation=True)
    )
    manager.saveBlankMask("blank", QSize(4, 4))
    manager.saveMaskToPath("save", tmp_path / "save.png")
    assert manager.activeSaveCount() == 2
    backend.run_all()
    assert manager.activeSaveCount() == 0
    runtime.shutdown()


def _dummy_canvas(
    *,
    mask_feature: bool = True,
    sam_manager: object | None = None,
    enabled: bool = True,
) -> SimpleNamespace:
    """Build a minimal autosave policy host."""
    workflow = SimpleNamespace(
        mask_feature_available=lambda: mask_feature,
        sam_feature_available=lambda: sam_manager is not None,
    )
    return SimpleNamespace(
        settings=MaskConfigSlice(mask_autosave_enabled=enabled),
        sam_manager=sam_manager,
        mask_service=SimpleNamespace() if mask_feature else None,
        mask_workflow=workflow,
    )


def test_autosave_feature_policy_requires_enabled_masks() -> None:
    """Autosave is available only for an enabled mask feature."""
    assert should_enable_mask_autosave(_dummy_canvas())
    assert not should_enable_mask_autosave(_dummy_canvas(enabled=False))
    assert not should_enable_mask_autosave(_dummy_canvas(mask_feature=False))
