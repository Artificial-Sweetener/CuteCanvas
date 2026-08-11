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

"""Lightweight tests for MaskService prefetch and activation decisions."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from cutecanvas import Config
from cutecanvas.core.config_features import MaskConfigSlice
from cutecanvas.masks import activation as activation_module
from cutecanvas.masks.live_preview_store import MaskLivePreviewStore
from cutecanvas.masks.mask import MaskAssetStore
from cutecanvas.masks.mask_controller import MaskController
from cutecanvas.masks.mask_service import MaskService
from cutecanvas.masks.render_products import (
    MaskPrefetchProduct,
    MaskSnippetProduct,
    PrefetchedOverlay,
)
from cutecanvas.resources import ProjectResourceStore
from PySide6.QtCore import QRect
from PySide6.QtGui import QImage
from qpane.types import DiagnosticRecord


def _build_service(qpane):
    manager = MaskAssetStore(ProjectResourceStore())
    controller = MaskController(
        manager,
        lambda point: point,
        Config(),
        mask_config=MaskConfigSlice(),
        live_previews=MaskLivePreviewStore(),
    )
    service = MaskService(
        qpane=qpane,
        mask_assets=manager,
        mask_controller=controller,
        config=Config(),
        mask_config=MaskConfigSlice(),
        view_execution_scope=qpane._execution_binding.scope,
        document_execution_scope=(
            qpane._execution_binding.document_runtime.execution_scope
        ),
        latest_requests=(
            qpane._execution_binding.document_runtime._latest_request_registry
        ),
    )
    return service, manager, controller


def _install_prefetch_request(service, image_id, revisions):
    """Install one pending prefetch identity for direct adoption tests."""
    request_id = uuid.uuid4()
    service.render_work._prefetch_handles[image_id] = SimpleNamespace(
        request_id=request_id,
        handle=None,
        mask_revisions=tuple(revisions),
    )
    return request_id


def _consume_prefetch(
    service,
    image_id,
    overlays,
    *,
    failures=(),
    duration_ms=1.0,
):
    """Adopt one direct prefetch product through current request identity."""
    request_id = _install_prefetch_request(
        service,
        image_id,
        ((overlay.mask_id, overlay.render_revision) for overlay in overlays),
    )
    service.render_work.consume_prefetch_results(
        request_id=request_id,
        product=MaskPrefetchProduct(
            image_id,
            tuple(overlays),
            tuple(failures),
            duration_ms,
        ),
    )
    return request_id


@pytest.mark.usefixtures("qapp")
def test_resolve_prefetch_scales_filters_invalid(canvas_core):
    """Invalid or duplicate scales should be filtered out."""
    service, _, _ = _build_service(canvas_core)
    scales = service.render_work.resolve_prefetch_scales(
        [
            1.0,
            0.5,
            0.5,
            0,
            "bad",
            0.25,
        ]
    )
    assert scales == (0.5, 0.25)


@pytest.mark.usefixtures("qapp")
def test_prefetch_skips_when_disabled_or_no_executor(canvas_core):
    """Prefetch should return False when disabled or executor is unavailable."""
    service, _, _ = _build_service(canvas_core)
    image_id = uuid.uuid4()
    service.setPrefetchEnabled(False)
    assert service.prefetchColorizedMasks(image_id) is False
    service.setPrefetchEnabled(True)
    service._executor = None
    assert service.prefetchColorizedMasks(image_id) is False


@pytest.mark.usefixtures("qapp")
def test_prefetch_skips_when_no_masks(canvas_core):
    """Empty mask lists should short-circuit prefetch."""
    service, _, _ = _build_service(canvas_core)
    image_id = uuid.uuid4()
    assert service.prefetchColorizedMasks(image_id) is False
    assert service.render_work.stats.skipped == 1


@pytest.mark.usefixtures("qapp")
def test_should_defer_activation_signals_for_small_ratio(canvas_core):
    """Large size drops should defer activation signals."""
    service, manager, _ = _build_service(canvas_core)
    prev_id = manager.create_mask(QImage(100, 100, QImage.Format_Grayscale8))
    next_id = manager.create_mask(QImage(10, 10, QImage.Format_Grayscale8))
    assert service._components.activation.should_defer(prev_id, next_id) is True


@pytest.mark.usefixtures("qapp")
def test_should_defer_activation_signals_skips_when_sizes_grow(canvas_core):
    """Growing or equal masks should not defer activation signals."""
    service, manager, _ = _build_service(canvas_core)
    prev_id = manager.create_mask(QImage(10, 10, QImage.Format_Grayscale8))
    next_id = manager.create_mask(QImage(100, 100, QImage.Format_Grayscale8))
    assert service._components.activation.should_defer(prev_id, next_id) is False


@pytest.mark.usefixtures("qapp")
def test_consume_prefetch_results_stashes_when_busy(canvas_core):
    """Busy masks should stash overlays and apply them once idle."""
    service, manager, controller = _build_service(canvas_core)
    mask_id = manager.create_mask(QImage(32, 32, QImage.Format_Grayscale8))
    overlay = PrefetchedOverlay(
        mask_id=mask_id,
        render_revision=controller.renders.render_revision(mask_id),
        image=QImage(32, 32, QImage.Format_ARGB32),
        scaled=(),
    )
    image_id = uuid.uuid4()
    request_id = _install_prefetch_request(
        service,
        image_id,
        ((mask_id, controller.renders.render_revision(mask_id)),),
    )
    controller.renders._async_pending[mask_id] = overlay.render_revision
    service._components.stroke_pipeline.is_mask_busy = lambda _mid: True
    service.render_work.consume_prefetch_results(
        request_id=request_id,
        product=MaskPrefetchProduct(image_id, (overlay,), (), 12.5),
    )
    assert mask_id in service.render_work._deferred_overlays
    assert controller.renders.has_pending_async(mask_id)
    service._components.stroke_pipeline.is_mask_busy = lambda _mid: False
    applied = service.render_work.apply_deferred(mask_id)
    assert applied is True
    assert not controller.renders.has_pending_async(mask_id)


@pytest.mark.usefixtures("qapp")
def test_deferred_prefetch_is_discarded_when_mask_revision_changes(canvas_core):
    """A pre-stroke overlay must not publish under the post-stroke cache key."""
    service, manager, controller = _build_service(canvas_core)
    mask_id = manager.create_mask(QImage(32, 32, QImage.Format_Grayscale8))
    overlay = PrefetchedOverlay(
        mask_id=mask_id,
        render_revision=controller.renders.render_revision(mask_id),
        image=QImage(32, 32, QImage.Format_ARGB32),
    )
    service.render_work._deferred_overlays[mask_id] = overlay
    controller.edits.advance_epoch(mask_id, reason="test-stroke")

    applied = service.render_work.apply_deferred(mask_id)

    assert applied is False
    assert mask_id not in service.render_work._deferred_overlays
    assert not controller.renders._cache


@pytest.mark.usefixtures("qapp")
def test_stale_prefetch_completion_preserves_replacement_handle(canvas_core):
    """An old completion must not consume a newer request for the same image."""
    service, _, _ = _build_service(canvas_core)
    image_id = uuid.uuid4()
    replacement = SimpleNamespace(
        request_id=uuid.uuid4(),
        handle=None,
        mask_revisions=(),
    )
    service.render_work._prefetch_handles[image_id] = replacement

    service.render_work.consume_prefetch_results(
        request_id=uuid.uuid4(),
        product=MaskPrefetchProduct(image_id, (), (), 1.0),
    )

    assert service.render_work._prefetch_handles[image_id] is replacement
    assert service.render_work.stats.completed == 0
    assert service.render_work.stats.failed == 0


@pytest.mark.usefixtures("qapp")
def test_prefetch_cancellation_balances_completed_worker_awaiting_ui(canvas_core):
    """A removed request must terminate even when its worker already completed."""
    service, manager, controller = _build_service(canvas_core)
    image_id = uuid.uuid4()
    mask_ids = tuple(
        manager.create_mask(QImage(8, 8, QImage.Format_Grayscale8)) for _ in range(2)
    )
    request_id = uuid.uuid4()
    handle = SimpleNamespace(cancel=lambda **_kwargs: False)
    service.render_work._prefetch_handles[image_id] = SimpleNamespace(
        request_id=request_id,
        handle=handle,
        mask_revisions=tuple(
            (mask_id, controller.renders.render_revision(mask_id))
            for mask_id in mask_ids
        ),
    )
    controller.renders.record_prefetch_request(2)
    for mask_id in mask_ids:
        controller.renders._async_pending[mask_id] = controller.renders.render_revision(
            mask_id
        )

    cancelled = service.cancelPrefetch(image_id)

    metrics = controller.renders.snapshot_metrics()
    assert cancelled is False
    assert metrics.prefetch_requested == 2
    assert metrics.prefetch_completed == 0
    assert metrics.prefetch_failed == 2
    assert request_id in service.render_work._cancelled_task_ids
    assert all(
        not controller.renders.has_pending_async(mask_id) for mask_id in mask_ids
    )

    service.render_work.consume_prefetch_results(
        request_id=request_id,
        product=MaskPrefetchProduct(image_id, (), (), 1.0),
    )

    metrics = controller.renders.snapshot_metrics()
    assert metrics.prefetch_failed == 2


@pytest.mark.usefixtures("qapp")
def test_pending_render_work_includes_every_mask_render_stage(canvas_core):
    """Render-idle state must include stroke, snippet, and prefetch ownership."""
    service, manager, controller = _build_service(canvas_core)
    mask_id = manager.create_mask(QImage(32, 32, QImage.Format_Grayscale8))
    image_id = uuid.uuid4()
    handle = SimpleNamespace()

    assert service.hasPendingRenderWork() is False

    service.render_work._snippet_handles[mask_id] = handle
    assert service.hasPendingRenderWork() is True
    service.render_work._snippet_handles.clear()

    service.render_work._prefetch_handles[image_id] = SimpleNamespace(
        handle=handle,
        mask_revisions=((mask_id, controller.renders.render_revision(mask_id)),),
    )
    assert service.hasPendingRenderWork() is True
    service.render_work._prefetch_handles.clear()

    service.render_work._deferred_overlays[mask_id] = PrefetchedOverlay(
        mask_id=mask_id,
        render_revision=0,
        image=QImage(32, 32, QImage.Format_ARGB32),
    )
    assert service.hasPendingRenderWork() is True

    service.render_work._deferred_overlays.clear()
    revision = controller.renders.render_revision(mask_id)
    controller.renders._async_pending[mask_id] = revision
    assert service.hasPendingRenderWork() is True


@pytest.mark.usefixtures("qapp")
def test_successful_prefetch_clears_async_colorize_ownership(canvas_core):
    """A committed prefetch must terminate the matching cache-miss lifecycle."""
    service, manager, controller = _build_service(canvas_core)
    mask_id = manager.create_mask(QImage(32, 32, QImage.Format_Grayscale8))
    image_id = uuid.uuid4()
    revision = controller.renders.render_revision(mask_id)
    controller.renders._async_pending[mask_id] = revision
    overlay = PrefetchedOverlay(
        mask_id=mask_id,
        render_revision=controller.renders.render_revision(mask_id),
        image=QImage(32, 32, QImage.Format_ARGB32),
    )

    _consume_prefetch(service, image_id, (overlay,))

    assert mask_id not in controller.renders._async_pending


@pytest.mark.usefixtures("qapp")
def test_stale_prefetch_cannot_clear_newer_async_colorize_ownership(canvas_core):
    """An old render completion must not finish a newer revision request."""
    service, manager, controller = _build_service(canvas_core)
    mask_id = manager.create_mask(QImage(32, 32, QImage.Format_Grayscale8))
    stale_revision = controller.renders.render_revision(mask_id)
    controller.edits.advance_epoch(mask_id, reason="newer-request")
    current_revision = controller.renders.render_revision(mask_id)
    controller.renders._async_pending[mask_id] = current_revision
    stale_overlay = PrefetchedOverlay(
        mask_id=mask_id,
        render_revision=stale_revision,
        image=QImage(32, 32, QImage.Format_ARGB32),
    )

    _consume_prefetch(service, uuid.uuid4(), (stale_overlay,))

    assert controller.renders.has_pending_async(mask_id)
    assert controller.renders._async_pending[mask_id] == current_revision


@pytest.mark.usefixtures("qapp")
def test_failed_prefetch_clears_matching_async_colorize_ownership(canvas_core):
    """A terminal overlay failure must release its matching render request."""
    service, manager, controller = _build_service(canvas_core)
    mask_id = manager.create_mask(QImage(32, 32, QImage.Format_Grayscale8))
    revision = controller.renders.render_revision(mask_id)
    controller.renders._async_pending[mask_id] = revision
    failed_overlay = PrefetchedOverlay(
        mask_id=mask_id,
        render_revision=revision,
        image=QImage(),
    )

    _consume_prefetch(
        service,
        uuid.uuid4(),
        (failed_overlay,),
        failures=((mask_id, "colorization failed"),),
    )

    assert not controller.renders.has_pending_async(mask_id)


@pytest.mark.usefixtures("qapp")
def test_snippet_result_is_discarded_while_stroke_preview_is_active(
    canvas_core,
    monkeypatch,
):
    """Background snippets must not overwrite a live provisional stroke."""
    service, manager, controller = _build_service(canvas_core)
    mask_id = manager.create_mask(QImage(32, 32, QImage.Format_Grayscale8))
    updates: list[object] = []
    monkeypatch.setattr(
        service._components.stroke_pipeline,
        "is_mask_busy",
        lambda candidate: candidate == mask_id,
    )
    monkeypatch.setattr(
        controller.renders,
        "update_region",
        lambda *args, **kwargs: updates.append((args, kwargs)),
    )

    request_id = uuid.uuid4()
    revision = controller.renders.render_revision(mask_id)
    service.render_work._snippet_handles[mask_id] = SimpleNamespace(
        request_id=request_id
    )
    service.render_work.consume_snippet_result(
        request_id=request_id,
        product=MaskSnippetProduct(
            mask_id,
            revision,
            manager.get_layer(mask_id).mask_image.rect(),
            QImage(32, 32, QImage.Format_ARGB32),
            0.0,
        ),
    )

    assert updates == []


@pytest.mark.usefixtures("qapp")
def test_durable_sampled_refresh_does_not_become_a_live_stroke_preview(
    canvas_core,
    monkeypatch,
) -> None:
    """Keep passive document refreshes out of provisional stroke ownership."""

    service, manager, controller = _build_service(canvas_core)
    mask_id = manager.create_mask(QImage(4096, 4096, QImage.Format.Format_Grayscale8))
    layer = manager.get_layer(mask_id)
    assert layer is not None
    monkeypatch.setattr(service.render_work, "_current_zoom", lambda: 0.125)

    service.render_work.update_region(QRect(512, 512, 128, 128), layer)

    assert not controller.renders.is_live_preview(mask_id)


@pytest.mark.usefixtures("qapp")
def test_missing_snippet_layer_clears_async_colorize_ownership(canvas_core):
    """A removed mask must not retain snippet-render ownership."""
    service, _manager, controller = _build_service(canvas_core)
    mask_id = uuid.uuid4()
    revision = controller.renders.render_revision(mask_id)
    controller.renders._async_pending[mask_id] = revision

    request_id = uuid.uuid4()
    service.render_work._snippet_handles[mask_id] = SimpleNamespace(
        request_id=request_id
    )
    service.render_work.consume_snippet_result(
        request_id=request_id,
        product=MaskSnippetProduct(
            mask_id,
            revision,
            QImage(4, 4, QImage.Format_Grayscale8).rect(),
            QImage(4, 4, QImage.Format_ARGB32),
            0.0,
        ),
    )

    assert not controller.renders.has_pending_async(mask_id)


@pytest.mark.usefixtures("qapp")
def test_schedule_activation_signals_warms_and_resumes(monkeypatch, canvas_core):
    """Activation scheduling should warm caches and resume overlays for pending ids."""
    service, manager, controller = _build_service(canvas_core)
    mask_id = manager.create_mask(QImage(12, 12, QImage.Format_Grayscale8))
    image_id = uuid.uuid4()
    service._components.activation._pending_compositions.add(image_id)
    warm_calls: list[uuid.UUID | None] = []
    emit_calls: list[uuid.UUID | None] = []
    pending_calls: list[uuid.UUID | None] = []
    resume_calls: list[uuid.UUID | None] = []
    resume_update_calls: list[uuid.UUID | None] = []

    monkeypatch.setattr(controller, "warm_mask", lambda mid: warm_calls.append(mid))
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
        activation_module.QTimer,
        "singleShot",
        lambda _ms, callback: callback(),
    )

    service._components.activation._schedule_signals(
        mask_id,
        warm_cache=True,
        composition_id=image_id,
    )

    assert pending_calls == [image_id]
    assert warm_calls == [mask_id]
    assert emit_calls == [mask_id]
    assert resume_update_calls == [image_id]
    assert resume_calls == []
    assert image_id not in service._components.activation._pending_compositions


@pytest.mark.usefixtures("qapp")
def test_mask_service_diagnostics_provider_aggregates_recent_messages(canvas_core):
    """Diagnostics should summarize recent status entries and prefetch stats."""
    service, _, controller = _build_service(canvas_core)
    service._components.status.record("Hidden", label="Mask")
    service._components.status.record(
        "Prefetch warmed 1 mask(s)",
        label="Mask Prefetch",
    )
    service._components.status.record("First issue", label="Mask Error")
    service._components.status.record("Second issue", label="Mask Error")
    controller.renders.record_prefetch_request(2)
    controller.renders.record_prefetch_completion(
        completed=1,
        failed=1,
        duration_ms=10.0,
    )
    service.render_work._last_message = "Prefetch warmed 1 mask(s)"
    service.render_work._last_duration_ms = 10.0

    records = service.diagnostics_records()
    assert all(isinstance(record, DiagnosticRecord) for record in records)
    labels = [record.label for record in records]
    assert "Mask" not in labels
    prefetch_record = records[-1]
    assert prefetch_record.label == "Mask|Prefetch"
    assert "scheduled=2 completed=1 skipped=0 failed=1" in prefetch_record.value
    error_record = next(record for record in records if record.label == "Mask Error")
    assert "(+1 earlier)" in error_record.value


@pytest.mark.usefixtures("qapp")
def test_request_async_colorize_falls_back_to_snippet(canvas_core):
    """Async colorize should schedule snippet work when prefetch misses."""
    service, manager, controller = _build_service(canvas_core)
    mask_id = manager.create_mask(QImage(8, 8, QImage.Format_Grayscale8))
    layer = manager.get_layer(mask_id)
    assert layer is not None
    calls: list[uuid.UUID] = []
    controller.renders.complete_async = lambda mid, _revision: calls.append(mid)
    service.render_work.prefetch = lambda *_args, **_kwargs: False
    service.render_work.schedule_snippet = lambda *_args, **_kwargs: False
    scheduled = service.render_work.request_async_colorize(mask_id, layer)
    assert scheduled is False
    assert calls == [mask_id]


@pytest.mark.usefixtures("qapp")
def test_invalidate_mask_cache_helpers_forward_to_controller(canvas_core):
    """Invalidate helpers should proxy to controller cache APIs."""
    service, _, controller = _build_service(canvas_core)
    mask_id = uuid.uuid4()
    image_id = uuid.uuid4()
    calls: list[tuple[str, object]] = []
    controller.renders.invalidate = lambda mid, **_kwargs: calls.append(("mask", mid))
    service.mask_ids_for_composition = lambda iid: [mask_id] if iid == image_id else []
    service.invalidateMaskCache(mask_id)
    service.invalidateMaskCachesForComposition(image_id)
    service.invalidateMaskCache(None)
    service.invalidateMaskCachesForComposition(None)
    assert ("mask", mask_id) in calls
    assert calls.count(("mask", mask_id)) == 2
