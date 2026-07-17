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

"""Lightweight tests for MaskService prefetch and activation decisions."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QImage

from qpane import Config
from qpane.core.config_features import MaskConfigSlice
from qpane.masks.mask import MaskManager
from qpane.masks.mask_controller import MaskController
from qpane.masks.mask_service import MaskService, PrefetchedOverlay
from qpane.masks import mask_service as mask_service_module
from qpane.types import DiagnosticRecord
from tests.helpers.executor_stubs import StubExecutor


def _build_service(qpane):
    manager = MaskManager()
    controller = MaskController(
        manager,
        lambda point: point,
        Config(),
        mask_config=MaskConfigSlice(),
    )
    service = MaskService(
        qpane=qpane,
        mask_manager=manager,
        mask_controller=controller,
        config=Config(),
        mask_config=MaskConfigSlice(),
        executor=StubExecutor(),
    )
    return service, manager, controller


@pytest.mark.usefixtures("qapp")
def test_resolve_prefetch_scales_filters_invalid(qpane_core):
    """Invalid or duplicate scales should be filtered out."""
    service, _, _ = _build_service(qpane_core)
    scales = service._resolve_prefetch_scales([1.0, 0.5, 0.5, 0, "bad", 0.25])
    assert scales == (0.5, 0.25)


@pytest.mark.usefixtures("qapp")
def test_prefetch_skips_when_disabled_or_no_executor(qpane_core):
    """Prefetch should return False when disabled or executor is unavailable."""
    service, _, _ = _build_service(qpane_core)
    image_id = uuid.uuid4()
    service.setPrefetchEnabled(False)
    assert service.prefetchColorizedMasks(image_id) is False
    service.setPrefetchEnabled(True)
    service._executor = None
    assert service.prefetchColorizedMasks(image_id) is False


@pytest.mark.usefixtures("qapp")
def test_prefetch_skips_when_no_masks(qpane_core):
    """Empty mask lists should short-circuit prefetch."""
    service, _, _ = _build_service(qpane_core)
    image_id = uuid.uuid4()
    assert service.prefetchColorizedMasks(image_id) is False
    assert service._prefetch_stats.skipped == 1


@pytest.mark.usefixtures("qapp")
def test_should_defer_activation_signals_for_small_ratio(qpane_core):
    """Large size drops should defer activation signals."""
    service, manager, _ = _build_service(qpane_core)
    prev_id = manager.create_mask(QImage(100, 100, QImage.Format_Grayscale8))
    next_id = manager.create_mask(QImage(10, 10, QImage.Format_Grayscale8))
    assert service._should_defer_activation_signals(prev_id, next_id) is True


@pytest.mark.usefixtures("qapp")
def test_should_defer_activation_signals_skips_when_sizes_grow(qpane_core):
    """Growing or equal masks should not defer activation signals."""
    service, manager, _ = _build_service(qpane_core)
    prev_id = manager.create_mask(QImage(10, 10, QImage.Format_Grayscale8))
    next_id = manager.create_mask(QImage(100, 100, QImage.Format_Grayscale8))
    assert service._should_defer_activation_signals(prev_id, next_id) is False


@pytest.mark.usefixtures("qapp")
def test_consume_prefetch_results_stashes_when_busy(qpane_core):
    """Busy masks should stash overlays and apply them once idle."""
    service, manager, controller = _build_service(qpane_core)
    mask_id = manager.create_mask(QImage(32, 32, QImage.Format_Grayscale8))
    overlay = PrefetchedOverlay(
        mask_id=mask_id,
        render_revision=controller.maskRenderRevision(mask_id),
        image=QImage(32, 32, QImage.Format_ARGB32),
        scaled=tuple(),
    )
    image_id = uuid.uuid4()
    service._prefetch_handles[image_id] = SimpleNamespace(
        handle=None,
        mask_revisions=((mask_id, controller.maskRenderRevision(mask_id)),),
    )
    controller._async_colorize_pending[mask_id] = overlay.render_revision
    service._stroke_pipeline.is_mask_busy = lambda _mid: True
    service._consume_prefetch_results(
        image_id=image_id,
        warmed=(overlay,),
        failures={},
        duration_ms=12.5,
        error=None,
        task_id=None,
    )
    assert mask_id in service._pending_prefetched_overlays
    assert controller.has_pending_async_colorize(mask_id)
    service._stroke_pipeline.is_mask_busy = lambda _mid: False
    applied = service._maybe_apply_pending_prefetch(mask_id)
    assert applied is True
    assert not controller.has_pending_async_colorize(mask_id)


@pytest.mark.usefixtures("qapp")
def test_deferred_prefetch_is_discarded_when_mask_revision_changes(qpane_core):
    """A pre-stroke overlay must not publish under the post-stroke cache key."""
    service, manager, controller = _build_service(qpane_core)
    mask_id = manager.create_mask(QImage(32, 32, QImage.Format_Grayscale8))
    overlay = PrefetchedOverlay(
        mask_id=mask_id,
        render_revision=controller.maskRenderRevision(mask_id),
        image=QImage(32, 32, QImage.Format_ARGB32),
    )
    service._pending_prefetched_overlays[mask_id] = overlay
    controller.bumpMaskGeneration(mask_id, reason="test-stroke")

    applied = service._maybe_apply_pending_prefetch(mask_id)

    assert applied is False
    assert mask_id not in service._pending_prefetched_overlays
    assert not controller._colorized_mask_cache


@pytest.mark.usefixtures("qapp")
def test_stale_prefetch_completion_preserves_replacement_handle(qpane_core):
    """An old completion must not consume a newer request for the same image."""
    service, _, _ = _build_service(qpane_core)
    image_id = uuid.uuid4()
    replacement = SimpleNamespace(
        handle=SimpleNamespace(task_id="replacement"),
        mask_revisions=tuple(),
    )
    service._prefetch_handles[image_id] = replacement

    service._consume_prefetch_results(
        image_id=image_id,
        warmed=(),
        failures={},
        duration_ms=1.0,
        error=None,
        task_id="stale",
    )

    assert service._prefetch_handles[image_id] is replacement
    assert service._prefetch_stats.completed == 0
    assert service._prefetch_stats.failed == 0


@pytest.mark.usefixtures("qapp")
def test_prefetch_cancellation_balances_completed_worker_awaiting_ui(qpane_core):
    """A removed request must terminate even when its worker already completed."""
    service, manager, controller = _build_service(qpane_core)
    image_id = uuid.uuid4()
    mask_ids = tuple(
        manager.create_mask(QImage(8, 8, QImage.Format_Grayscale8)) for _ in range(2)
    )
    handle = SimpleNamespace(task_id="worker-complete")
    service._prefetch_handles[image_id] = SimpleNamespace(
        handle=handle,
        mask_revisions=tuple(
            (mask_id, controller.maskRenderRevision(mask_id)) for mask_id in mask_ids
        ),
    )
    controller.record_prefetch_request(2)
    for mask_id in mask_ids:
        controller._async_colorize_pending[mask_id] = controller.maskRenderRevision(
            mask_id
        )

    cancelled = service.cancelPrefetch(image_id)

    metrics = controller.snapshot_metrics()
    assert cancelled is False
    assert metrics.prefetch_requested == 2
    assert metrics.prefetch_completed == 0
    assert metrics.prefetch_failed == 2
    assert handle.task_id in service._cancelled_prefetch_tasks
    assert all(
        not controller.has_pending_async_colorize(mask_id) for mask_id in mask_ids
    )

    service._consume_prefetch_results(
        image_id=image_id,
        warmed=(),
        failures={},
        duration_ms=1.0,
        error=None,
        task_id=handle.task_id,
    )

    metrics = controller.snapshot_metrics()
    assert metrics.prefetch_failed == 2


@pytest.mark.usefixtures("qapp")
def test_pending_render_work_includes_every_mask_render_stage(qpane_core):
    """Render-idle state must include stroke, snippet, and prefetch ownership."""
    service, manager, controller = _build_service(qpane_core)
    mask_id = manager.create_mask(QImage(32, 32, QImage.Format_Grayscale8))
    image_id = uuid.uuid4()
    handle = SimpleNamespace(task_id="pending")

    assert service.hasPendingRenderWork() is False

    service._snippet_handles[mask_id] = handle
    assert service.hasPendingRenderWork() is True
    service._snippet_handles.clear()

    service._prefetch_handles[image_id] = SimpleNamespace(
        handle=handle,
        mask_revisions=((mask_id, controller.maskRenderRevision(mask_id)),),
    )
    assert service.hasPendingRenderWork() is True
    service._prefetch_handles.clear()

    service._pending_prefetched_overlays[mask_id] = PrefetchedOverlay(
        mask_id=mask_id,
        render_revision=0,
        image=QImage(32, 32, QImage.Format_ARGB32),
    )
    assert service.hasPendingRenderWork() is True

    service._pending_prefetched_overlays.clear()
    revision = controller.maskRenderRevision(mask_id)
    controller._async_colorize_pending[mask_id] = revision
    assert service.hasPendingRenderWork() is True


@pytest.mark.usefixtures("qapp")
def test_successful_prefetch_clears_async_colorize_ownership(qpane_core):
    """A committed prefetch must terminate the matching cache-miss lifecycle."""
    service, manager, controller = _build_service(qpane_core)
    mask_id = manager.create_mask(QImage(32, 32, QImage.Format_Grayscale8))
    image_id = uuid.uuid4()
    revision = controller.maskRenderRevision(mask_id)
    controller._async_colorize_pending[mask_id] = revision
    overlay = PrefetchedOverlay(
        mask_id=mask_id,
        render_revision=controller.maskRenderRevision(mask_id),
        image=QImage(32, 32, QImage.Format_ARGB32),
    )

    service._consume_prefetch_results(
        image_id=image_id,
        warmed=(overlay,),
        failures={},
        duration_ms=1.0,
        error=None,
        task_id=None,
    )

    assert mask_id not in controller._async_colorize_pending


@pytest.mark.usefixtures("qapp")
def test_stale_prefetch_cannot_clear_newer_async_colorize_ownership(qpane_core):
    """An old render completion must not finish a newer revision request."""
    service, manager, controller = _build_service(qpane_core)
    mask_id = manager.create_mask(QImage(32, 32, QImage.Format_Grayscale8))
    stale_revision = controller.maskRenderRevision(mask_id)
    controller.bumpMaskGeneration(mask_id, reason="newer-request")
    current_revision = controller.maskRenderRevision(mask_id)
    controller._async_colorize_pending[mask_id] = current_revision
    stale_overlay = PrefetchedOverlay(
        mask_id=mask_id,
        render_revision=stale_revision,
        image=QImage(32, 32, QImage.Format_ARGB32),
    )

    service._consume_prefetch_results(
        image_id=uuid.uuid4(),
        warmed=(stale_overlay,),
        failures={},
        duration_ms=1.0,
        error=None,
        task_id=None,
    )

    assert controller.has_pending_async_colorize(mask_id)
    assert controller._async_colorize_pending[mask_id] == current_revision


@pytest.mark.usefixtures("qapp")
def test_failed_prefetch_clears_matching_async_colorize_ownership(qpane_core):
    """A terminal overlay failure must release its matching render request."""
    service, manager, controller = _build_service(qpane_core)
    mask_id = manager.create_mask(QImage(32, 32, QImage.Format_Grayscale8))
    revision = controller.maskRenderRevision(mask_id)
    controller._async_colorize_pending[mask_id] = revision
    failed_overlay = PrefetchedOverlay(
        mask_id=mask_id,
        render_revision=revision,
        image=QImage(),
    )

    service._consume_prefetch_results(
        image_id=uuid.uuid4(),
        warmed=(failed_overlay,),
        failures={mask_id: "colorization failed"},
        duration_ms=1.0,
        error=None,
        task_id=None,
    )

    assert not controller.has_pending_async_colorize(mask_id)


@pytest.mark.usefixtures("qapp")
def test_snippet_result_is_discarded_while_stroke_preview_is_active(
    qpane_core,
    monkeypatch,
):
    """Background snippets must not overwrite a live provisional stroke."""
    service, manager, controller = _build_service(qpane_core)
    mask_id = manager.create_mask(QImage(32, 32, QImage.Format_Grayscale8))
    updates: list[object] = []
    monkeypatch.setattr(
        service._stroke_pipeline,
        "is_mask_busy",
        lambda candidate: candidate == mask_id,
    )
    monkeypatch.setattr(
        controller,
        "updateMaskRegion",
        lambda *args, **kwargs: updates.append((args, kwargs)),
    )

    service._consume_snippet_result(
        mask_id=mask_id,
        render_revision=controller.maskRenderRevision(mask_id),
        handle=None,
        dirty_rect=manager.get_layer(mask_id).mask_image.rect(),
        colorized_image=QImage(32, 32, QImage.Format_ARGB32),
    )

    assert updates == []


@pytest.mark.usefixtures("qapp")
def test_missing_snippet_layer_clears_async_colorize_ownership(qpane_core):
    """A removed mask must not retain snippet-render ownership."""
    service, _manager, controller = _build_service(qpane_core)
    mask_id = uuid.uuid4()
    revision = controller.maskRenderRevision(mask_id)
    controller._async_colorize_pending[mask_id] = revision

    service._consume_snippet_result(
        mask_id=mask_id,
        render_revision=revision,
        handle=None,
        dirty_rect=QImage(4, 4, QImage.Format_Grayscale8).rect(),
        colorized_image=QImage(4, 4, QImage.Format_ARGB32),
    )

    assert not controller.has_pending_async_colorize(mask_id)


@pytest.mark.usefixtures("qapp")
def test_schedule_activation_signals_warms_and_resumes(monkeypatch, qpane_core):
    """Activation scheduling should warm caches and resume overlays for pending ids."""
    service, manager, controller = _build_service(qpane_core)
    mask_id = manager.create_mask(QImage(12, 12, QImage.Format_Grayscale8))
    image_id = uuid.uuid4()
    service._pending_activation_images.add(image_id)
    warm_calls: list[uuid.UUID | None] = []
    emit_calls: list[uuid.UUID | None] = []
    pending_calls: list[uuid.UUID | None] = []
    resume_calls: list[uuid.UUID | None] = []
    resume_update_calls: list[uuid.UUID | None] = []

    monkeypatch.setattr(controller, "warmMaskCache", lambda mid: warm_calls.append(mid))
    monkeypatch.setattr(
        controller,
        "emit_activation_signals",
        lambda mid: emit_calls.append(mid),
    )
    service.set_activation_resume_hooks(
        lambda image_id=None: resume_calls.append(image_id),
        lambda image_id=None: resume_update_calls.append(image_id),
        lambda image_id=None: pending_calls.append(image_id),
    )
    monkeypatch.setattr(
        mask_service_module.QTimer,
        "singleShot",
        lambda _ms, callback: callback(),
    )

    service._schedule_activation_signals(
        mask_id,
        warm_cache=True,
        image_id=image_id,
    )

    assert pending_calls == [image_id]
    assert warm_calls == [mask_id]
    assert emit_calls == [mask_id]
    assert resume_update_calls == [image_id]
    assert resume_calls == []
    assert image_id not in service._pending_activation_images


@pytest.mark.usefixtures("qapp")
def test_mask_service_diagnostics_provider_aggregates_recent_messages(qpane_core):
    """Diagnostics should summarize recent status entries and prefetch stats."""
    service, _, _ = _build_service(qpane_core)
    service._status_messages.clear()
    service._status_messages.append(("Mask", "Hidden"))
    service._status_messages.append(("Mask Prefetch", "Prefetch warmed 1 mask(s)"))
    service._status_messages.append(("Mask Error", "First issue"))
    service._status_messages.append(("Mask Error", "Second issue"))
    service._prefetch_stats.scheduled = 2
    service._prefetch_stats.completed = 1
    service._prefetch_stats.skipped = 0
    service._prefetch_stats.failed = 1
    service._prefetch_stats.last_message = "Prefetch warmed 1 mask(s)"
    service._prefetch_stats.last_duration_ms = 10.0

    records = service._diagnostics_provider(qpane_core)
    assert all(isinstance(record, DiagnosticRecord) for record in records)
    labels = [record.label for record in records]
    assert "Mask" not in labels
    prefetch_record = records[-1]
    assert prefetch_record.label == "Mask|Prefetch"
    assert "scheduled=2 completed=1 skipped=0 failed=1" in prefetch_record.value
    error_record = next(record for record in records if record.label == "Mask Error")
    assert "(+1 earlier)" in error_record.value


@pytest.mark.usefixtures("qapp")
def test_request_async_colorize_falls_back_to_snippet(qpane_core):
    """Async colorize should schedule snippet work when prefetch misses."""
    service, manager, controller = _build_service(qpane_core)
    mask_id = manager.create_mask(QImage(8, 8, QImage.Format_Grayscale8))
    layer = manager.get_layer(mask_id)
    assert layer is not None
    calls: list[uuid.UUID] = []
    controller.notify_async_colorize_complete = lambda mid, _revision: calls.append(mid)
    service.prefetchColorizedMasks = lambda *_args, **_kwargs: False
    service._schedule_snippet_colorize = lambda *_args, **_kwargs: False
    scheduled = service._request_async_colorize(mask_id, layer)
    assert scheduled is False
    assert calls == [mask_id]


@pytest.mark.usefixtures("qapp")
def test_invalidate_mask_cache_helpers_forward_to_controller(qpane_core):
    """Invalidate helpers should proxy to controller cache APIs."""
    service, _, controller = _build_service(qpane_core)
    mask_id = uuid.uuid4()
    image_id = uuid.uuid4()
    calls: list[tuple[str, object]] = []
    controller.invalidate_mask_cache = lambda mid: calls.append(("mask", mid))
    controller.invalidate_image_cache = lambda iid: calls.append(("image", iid))
    service.invalidateMaskCache(mask_id)
    service.invalidateMaskCachesForImage(image_id)
    service.invalidateMaskCache(None)
    service.invalidateMaskCachesForImage(None)
    assert ("mask", mask_id) in calls
    assert ("image", image_id) in calls
