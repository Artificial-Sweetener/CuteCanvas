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

"""Tests covering mask autosave scheduling, execution, and error handling."""

import time
from pathlib import Path
from types import SimpleNamespace

from cutecanvas import Config
from cutecanvas.core.config_features import MaskConfigSlice
from cutecanvas.masks import autosave
from cutecanvas.masks.autosave import AutosaveManager
from cutecanvas.masks.install import should_enable_mask_autosave
from PySide6.QtCore import QBuffer, QIODevice, QObject, QSize
from PySide6.QtGui import QImage, Qt
from qpane.concurrency import TaskRejected

from tests.helpers.executor_stubs import RejectingStubExecutor, StubExecutor


class DummyTimer:
    def __init__(self):
        self.started_interval = None

    def start(self, interval):
        self.started_interval = interval


class DummySignal:
    """Lightweight signal stub for tests."""

    def __init__(self):
        self.handlers = []

    def connect(self, handler):
        self.handlers.append(handler)

    def emit(self, *args, **kwargs):
        for handler in list(self.handlers):
            handler(*args, **kwargs)


class DummyWorker:
    """Mask save worker stub that records deletion flags."""

    def __init__(self, image_payload, path, mask_id):
        if isinstance(image_payload, bytes):
            self.image_bytes = image_payload
        else:
            buffer = QBuffer()
            if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
                raise RuntimeError("QBuffer failed to open in DummyWorker")
            if not image_payload.save(buffer, "PNG"):
                raise RuntimeError("QImage.save returned False in DummyWorker")
            self.image_bytes = bytes(buffer.data())
            buffer.close()
        self.path = Path(path)
        self.mask_id = mask_id
        self.finished = DummySignal()
        self.auto_delete = None

    def setAutoDelete(self, value):
        self.auto_delete = value

    def run(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(self.image_bytes)
        self.finished.emit(self)


def _build_manager(
    settings,
    *,
    image_path: Path | None = None,
    executor=None,
):
    if executor is None:
        executor = StubExecutor(auto_finish=True)
    qpane_parent = QObject()
    dummy_layer = SimpleNamespace(mask_image=QImage(2, 2, QImage.Format_ARGB32))
    dummy_layer.mask_image.fill(Qt.white)
    manager = AutosaveManager(
        snapshot_provider=lambda _mask_id: dummy_layer.mask_image,
        settings=settings,
        get_current_image_path=lambda: image_path or Path("/tmp/example.png"),
        executor=executor,
        parent=qpane_parent,
    )
    manager._autosave_timer = DummyTimer()
    return manager, qpane_parent


def test_schedule_save_noop_when_disabled(qapp):
    settings = Config()
    settings.mask_autosave_enabled = False
    manager, _ = _build_manager(settings)
    manager.scheduleSave("mask-1")
    assert manager._dirty_masks_for_autosave == set()
    assert manager._autosave_timer.started_interval is None


def test_schedule_save_records_when_enabled(qapp):
    settings = Config()
    settings.mask_autosave_enabled = True
    manager, _ = _build_manager(settings)
    manager.scheduleSave("mask-123")
    assert manager._dirty_masks_for_autosave == {"mask-123"}
    assert (
        manager._autosave_timer.started_interval == settings.mask_autosave_debounce_ms
    )


def test_perform_save_uses_template_path(monkeypatch, tmp_path, qapp):
    settings = Config()
    settings.mask_autosave_enabled = True
    settings.mask_autosave_path_template = str(tmp_path / "{image_name}-{mask_id}.png")
    executor = StubExecutor(auto_finish=True)
    manager, _ = _build_manager(
        settings,
        image_path=tmp_path / "example.png",
        executor=executor,
    )
    manager._dirty_masks_for_autosave.add("mask-42")
    monkeypatch.setattr(autosave, "_MaskSaveWorker", DummyWorker)
    calls: list[tuple[str, Path]] = []
    original_save = manager.saveMaskToPath

    def record_save(mask_id, path):
        calls.append((mask_id, path))
        return original_save(mask_id, path)

    monkeypatch.setattr(manager, "saveMaskToPath", record_save)
    manager.performSave()
    expected_path = tmp_path / "example-mask-42.png"
    assert calls == [("mask-42", expected_path)]
    assert expected_path.exists()
    assert manager._dirty_masks_for_autosave == set()


def test_save_blank_mask_enqueue_worker(qapp, monkeypatch, tmp_path):
    settings = Config()
    settings.mask_autosave_enabled = True
    settings.mask_autosave_on_creation = True
    settings.mask_autosave_path_template = str(tmp_path / "{image_name}-{mask_id}.png")
    executor = StubExecutor()
    manager, _ = _build_manager(settings, executor=executor)
    monkeypatch.setattr(autosave, "_MaskSaveWorker", DummyWorker)
    manager.saveBlankMask("mask-xyz", QSize(4, 4))
    pending = list(executor.pending_tasks())
    assert pending, "Blank mask encode worker should be queued"
    encode_record = pending[0]
    assert isinstance(encode_record.runnable, autosave._BlankMaskEncodeWorker)
    executor.run_task(encode_record.handle.task_id)
    qapp.processEvents()
    pending_after = list(executor.pending_tasks())
    assert pending_after, "Mask save worker should be scheduled after encode"
    save_record = pending_after[0]
    worker = save_record.runnable
    assert isinstance(worker, DummyWorker)
    assert worker.mask_id == "mask-xyz"
    assert worker.path.name.startswith("example-mask-xyz")
    assert worker.auto_delete is False
    assert worker in manager._active_workers


def test_save_blank_mask_emits_failure_when_encode_fails(monkeypatch, tmp_path, qapp):
    settings = Config()
    settings.mask_autosave_enabled = True
    settings.mask_autosave_on_creation = True
    settings.mask_autosave_path_template = str(tmp_path / "{image_name}-{mask_id}.png")
    executor = StubExecutor()
    manager = AutosaveManager(
        snapshot_provider=lambda _mask_id: None,
        settings=settings,
        get_current_image_path=lambda: tmp_path / "image.png",
        executor=executor,
        parent=None,
    )
    manager._autosave_timer = DummyTimer()
    failures: list[tuple[str, str, Exception]] = []
    manager.saveFailed.connect(
        lambda mask_id, path, exc: failures.append((mask_id, path, exc))
    )
    queue_calls: list[tuple] = []
    monkeypatch.setattr(
        manager,
        "_queue_save_worker",
        lambda *args, **kwargs: queue_calls.append(args),
    )

    class FakeQImage:
        Format_ARGB32_Premultiplied = object()

        def __init__(self, *_args, **_kwargs):
            pass

        def fill(self, *_args, **_kwargs):
            return None

        def save(self, *_args, **_kwargs):
            return False

    monkeypatch.setattr(autosave, "QImage", FakeQImage)
    manager.saveBlankMask("mask-err", QSize(4, 4))
    pending = list(executor.pending_tasks())
    assert pending, "Encode worker should be queued even on failure"
    encode_record = pending[0]
    executor.run_task(encode_record.handle.task_id)
    qapp.processEvents()
    assert queue_calls == []
    assert len(failures) == 1
    mask_id, path, exc = failures[0]
    assert mask_id == "mask-err"
    assert path == str(tmp_path / "image-mask-err.png")
    assert isinstance(exc, RuntimeError)


def test_blank_encode_rejection_queues_retry(tmp_path, qapp):
    settings = Config()
    settings.mask_autosave_enabled = True
    executor = StubExecutor()
    manager = AutosaveManager(
        snapshot_provider=lambda _mask_id: None,
        settings=settings,
        get_current_image_path=lambda: tmp_path / "image.png",
        executor=executor,
        parent=None,
    )
    queued: list[tuple[str, tuple[str, tuple[int, int], Path]]] = []

    class _DummyRetry:
        def queueOrCoalesce(self, key, payload, submit, coalesce, throttle):
            queued.append((key, payload))

    manager._retry = _DummyRetry()
    throttled: list[tuple[str, str, int]] = []
    manager.saveThrottled.connect(
        lambda mask_id, path, attempt: throttled.append((mask_id, path, attempt))
    )
    rejection = TaskRejected(
        "reject",
        category="autosave",
        device=None,
        limit_type="category",
        limit_value=1,
        pending_total=1,
        pending_category=1,
    )
    manager._handle_blank_encode_rejection(
        mask_id="mask-1",
        size=(4, 4),
        path=Path("mask.png"),
        attempt=1,
        rejection=rejection,
    )
    assert throttled == [("mask-1", "mask.png", 2)]
    assert queued == [("blank::mask-1", ("mask-1", (4, 4), Path("mask.png")))]


def test_save_mask_to_path_emits_failure_payload(monkeypatch, tmp_path, qapp):
    settings = Config()
    settings.mask_autosave_enabled = True
    executor = StubExecutor(auto_finish=True)
    manager, _ = _build_manager(settings, executor=executor)

    class FakeCopy:
        def isNull(self):
            return False

        def save(self, *_args, **_kwargs):
            return False

    manager._snapshot_provider = lambda _mask_id: FakeCopy()
    failures: list[tuple[str, str, Exception]] = []
    manager.saveFailed.connect(
        lambda mask_id, path, exc: failures.append((mask_id, path, exc))
    )
    manager.saveMaskToPath("mask-err", tmp_path / "failure.png")
    qapp.processEvents()
    assert len(failures) == 1
    mask_id, path, exc = failures[0]
    assert mask_id == "mask-err"
    assert path == str(tmp_path / "failure.png")
    assert isinstance(exc, RuntimeError)


def _build_dummy_qpane(
    *, mask_feature: bool = True, sam_manager=None, enabled: bool = True
):
    """Construct a minimal CuteCanvas stand-in for mask autosave tests."""
    mask_settings = MaskConfigSlice(mask_autosave_enabled=enabled)
    mask_service = SimpleNamespace() if mask_feature else None
    workflow = SimpleNamespace(
        mask_feature_available=lambda: mask_feature,
        sam_feature_available=lambda: sam_manager is not None,
    )
    return SimpleNamespace(
        settings=mask_settings,
        sam_manager=sam_manager,
        mask_service=mask_service,
        mask_workflow=workflow,
    )


def test_should_enable_mask_autosave_enabled_with_mask():
    qpane = _build_dummy_qpane()
    assert should_enable_mask_autosave(qpane)


def test_should_enable_mask_autosave_disabled_flag():
    qpane = _build_dummy_qpane(enabled=False)
    assert not should_enable_mask_autosave(qpane)


def test_should_enable_mask_autosave_requires_mask_feature():
    qpane = _build_dummy_qpane(mask_feature=False)
    assert not should_enable_mask_autosave(qpane)


def test_autosave_manager_submits_io_task(tmp_path, qapp):
    """AutosaveManager should submit IO tasks via the shared executor."""
    settings = Config()
    settings.mask_autosave_enabled = True
    mask_image = QImage(4, 4, QImage.Format_ARGB32)
    mask_image.fill(Qt.white)
    executor = StubExecutor()
    manager = AutosaveManager(
        snapshot_provider=lambda _mask_id: mask_image,
        settings=settings,
        get_current_image_path=lambda: tmp_path / "image.png",
        executor=executor,
    )
    destination = tmp_path / "mask.png"
    manager.saveMaskToPath("mask-1", str(destination))
    pending = list(executor.pending_tasks())
    assert pending and pending[0].handle.category == "io"
    executor.run_task(pending[0].handle.task_id)
    qapp.processEvents()
    assert executor.finished, "Autosave worker should finish"
    assert manager.activeSaveCount() == 0
    assert destination.exists()
    manager.shutdown()


def test_cancel_pending_mask_requests_executor_cancellation(tmp_path):
    """Cancelling a pending autosave should call executor.cancel."""
    settings = Config()
    settings.mask_autosave_enabled = True
    mask_image = QImage(4, 4, QImage.Format_ARGB32)
    mask_image.fill(Qt.white)
    executor = StubExecutor()
    manager = AutosaveManager(
        snapshot_provider=lambda _mask_id: mask_image,
        settings=settings,
        get_current_image_path=lambda: tmp_path / "image.png",
        executor=executor,
    )
    destination = tmp_path / "mask-cancel.png"
    manager.saveMaskToPath("mask-2", str(destination))
    pending = list(executor.pending_tasks())
    assert pending, "Expected a queued autosave task"
    handle = pending[0].handle
    manager.cancelPendingMask("mask-2")
    assert handle in executor.cancelled
    assert "mask-2" not in manager._active_entries
    manager.shutdown()


def test_autosave_retries_after_throttle(tmp_path, qapp):
    """AutosaveManager should resubmit saves after TaskRejected."""
    settings = Config()
    settings.mask_autosave_enabled = True
    settings.mask_autosave_path_template = str(tmp_path / "{image_name}-{mask_id}.png")
    executor = RejectingStubExecutor(reject_counts={"io": 1})
    manager, _ = _build_manager(
        settings, image_path=tmp_path / "example.png", executor=executor
    )
    target_path = tmp_path / "mask-output.png"
    throttled: list[tuple[str, str, int]] = []
    manager.saveThrottled.connect(
        lambda mask_id, path, attempt: throttled.append((mask_id, path, attempt))
    )
    manager.saveMaskToPath("mask-a", target_path)
    assert throttled == [("mask-a", str(target_path), 1)]
    assert executor.rejections

    def wait_for(predicate, *, timeout: float = 1.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            qapp.processEvents()
            if predicate():
                return
            time.sleep(0.01)
        raise AssertionError("condition was not met before timeout")

    wait_for(
        lambda: any(
            record.handle.category == "io" for record in executor.pending_tasks()
        )
    )
    pending = list(executor.pending_tasks())
    assert pending
    executor.run_task(pending[0].handle.task_id)
    wait_for(target_path.exists)
    assert target_path.exists()
    assert not manager._retry.pendingKeys(), "autosave retries should be cleared"


def test_save_blank_mask_skips_when_path_exists(tmp_path, qapp):
    settings = Config()
    settings.mask_autosave_enabled = True
    settings.mask_autosave_on_creation = True
    settings.mask_autosave_path_template = str(tmp_path / "{image_name}-{mask_id}.png")
    executor = StubExecutor()
    manager, _ = _build_manager(
        settings, image_path=tmp_path / "example.png", executor=executor
    )
    existing_path = tmp_path / "example-mask-abc.png"
    existing_path.write_bytes(b"already-exists")
    manager.saveBlankMask("mask-abc", QSize(16, 16))
    assert list(executor.pending_tasks()) == []
