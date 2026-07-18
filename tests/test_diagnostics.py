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

"""Tests for diagnostics registration and overlay sampling."""

import logging
import uuid
from types import SimpleNamespace

from qpane import QPane
from qpane.cache import cache_detail_provider, cache_diagnostics_provider
from qpane.concurrency.retry import RetryCategorySnapshot, RetrySnapshot
from qpane.core.config_features import MaskConfigSlice
from qpane.masks.mask_diagnostics import (
    MaskStrokeDiagnosticsSnapshot,
    MaskStrokeJobSnapshot,
    MaskStrokeResultSnapshot,
    mask_brush_detail_provider,
    mask_job_detail_provider,
    mask_summary_provider,
)
from qpane.masks.sam_feature import (
    _sam_summary_diagnostics_provider,
)
from qpane.swap.coordinator import SwapCoordinatorMetrics
from qpane.swap.diagnostics import swap_progress_provider
from qpane.types import DiagnosticRecord


def test_diagnostics_cached_snapshot_reuses_provider(qapp):
    qpane = QPane(features=())
    try:
        calls = {"count": 0}

        def provider(_qpane):
            calls["count"] += 1
            return (DiagnosticRecord("Counter", str(calls["count"])),)

        qpane.hooks.register_diagnostics_provider(provider, domain="custom.counter")
        diagnostics = qpane.diagnostics()
        diagnostics.cached_snapshot(force=True)
        assert calls["count"] == 1
        diagnostics.cached_snapshot()
        assert calls["count"] == 1
        diagnostics.set_dirty("custom.counter")
        diagnostics.cached_snapshot()
        assert calls["count"] == 2
        qpane.gatherDiagnostics()
        assert calls["count"] == 3
    finally:
        qpane.deleteLater()
        qapp.processEvents()


def test_qpane_core_diagnostics_contains_baseline(qapp):
    qpane = QPane(features=())
    try:
        snapshot = qpane.gatherDiagnostics()
        rendered = snapshot.renderStrings()
        assert any(item.startswith("Paint:") for item in rendered)
        assert any(item.startswith("Zoom:") for item in rendered)
    finally:
        qpane.deleteLater()
        qapp.processEvents()


def test_hooks_can_register_custom_diagnostics(qapp):
    qpane = QPane(features=())
    try:
        qpane.hooks.register_diagnostics_provider(
            lambda p: (DiagnosticRecord("Custom", "42"),)
        )
        snapshot = qpane.gatherDiagnostics()
        assert "Custom: 42" in snapshot.renderStrings()
    finally:
        qpane.deleteLater()
        qapp.processEvents()


def test_registry_logs_provider_failures_once(qapp, caplog):
    qpane = QPane(features=())
    try:

        def flaky_provider(_):
            yield DiagnosticRecord("Temp", "42")
            raise RuntimeError("boom")

        qpane.hooks.register_diagnostics_provider(flaky_provider)
        with caplog.at_level(logging.WARNING, logger="qpane.core.diagnostics"):
            snapshot = qpane.gatherDiagnostics()
            snapshot_again = qpane.gatherDiagnostics()
        assert "Temp: 42" not in snapshot.renderStrings()
        assert "Temp: 42" not in snapshot_again.renderStrings()
        warning_messages = [record.getMessage() for record in caplog.records]
        assert (
            sum("Diagnostics provider" in message for message in warning_messages) == 1
        )
    finally:
        qpane.deleteLater()
        qapp.processEvents()


def test_mask_summary_provider_summarises_state():
    mask_manager = SimpleNamespace(
        get_mask_ids_for_image=lambda _: ["mask-1", "mask-2", "mask-3"]
    )

    class FakeCatalog:
        def __init__(self):
            self._current_id = "image-1"

        def currentImageID(self):
            return self._current_id

        def maskManager(self):
            return mask_manager

    class FakeMaskService:
        def __init__(self):
            self.manager = mask_manager

        def getActiveMaskId(self):
            return "mask-2"

        def get_latest_status_message(self, *labels: str):
            label_set = set(labels)
            if {"Mask Autosave", "Mask Autosave Error"} & label_set:
                return "Mask Autosave", "autosaved"
            if {"Mask", "Mask Error"} & label_set:
                return "Mask", "created"
            return None

        def strokeDiagnosticsSnapshot(self):
            return None

    catalog = FakeCatalog()
    autosave_manager = object()
    qpane = SimpleNamespace(
        catalog=lambda: catalog,
        mask_service=FakeMaskService(),
        autosaveManager=lambda: autosave_manager,
        settings=MaskConfigSlice(mask_autosave_enabled=True),
        interaction=SimpleNamespace(brush_size=12, alt_key_held=True),
    )
    records = mask_summary_provider(qpane)
    assert DiagnosticRecord("Mask", "created") in records
    assert DiagnosticRecord("Mask Layers", "3 (active=mask-2)") in records
    assert DiagnosticRecord("Mask Autosave", "autosaved") in records
    brush_records = mask_brush_detail_provider(qpane)
    assert DiagnosticRecord("Mask|Brush", "12") in brush_records
    assert DiagnosticRecord("Mask|Brush Mode", "Erase") in brush_records


def test_mask_summary_provider_returns_empty_without_service():
    qpane = SimpleNamespace(mask_service=None)
    assert mask_summary_provider(qpane) == ()


def test_mask_job_detail_provider_reports_job_metrics():
    mask_manager = SimpleNamespace(
        get_mask_ids_for_image=lambda _: ["mask-1"],
    )

    class FakeCatalog:
        def __init__(self):
            self._current_id = "image-1"

        def currentImageID(self):
            return self._current_id

        def maskManager(self):
            return mask_manager

    class FakeMaskService:
        def __init__(self):
            self.manager = mask_manager

        def getActiveMaskId(self):
            return "mask-1"

        def get_latest_status_message(self, *labels: str):
            return None

        def strokeDiagnosticsSnapshot(self):
            return snapshot

    mask_id = uuid.uuid4()
    snapshot = MaskStrokeDiagnosticsSnapshot(
        outstanding=(
            MaskStrokeJobSnapshot(
                mask_id=mask_id,
                job_token=7,
                generation=3,
                age_ms=42.0,
                source="paint",
                stride=2,
                pending_count=1,
            ),
        ),
        drop_counts={"forced_drop": 2},
        generation_events={"rebased": 1},
        last_result=MaskStrokeResultSnapshot(
            status="committed",
            mask_id=mask_id,
            job_token=7,
            duration_ms=30.0,
            detail="commit",
        ),
    )
    catalog = FakeCatalog()
    qpane = SimpleNamespace(
        catalog=lambda: catalog,
        _catalog=catalog,
        mask_service=FakeMaskService(),
        autosave_manager=object(),
        settings=MaskConfigSlice(mask_autosave_enabled=True),
        interaction=SimpleNamespace(brush_size=9, alt_key_held=False),
    )
    records = mask_job_detail_provider(qpane)
    badge_values = [
        record.value for record in records if record.label == "Mask Jobs|Badge"
    ]
    assert any("pending" in value for value in badge_values)
    assert any(record.label == "Mask Jobs|Outstanding" for record in records)
    assert any(
        record.label == "Mask Jobs|Drops" and "forced_drop=2" in record.value
        for record in records
    )
    assert any(
        record.label == "Mask Jobs|Last" and "committed" in record.value
        for record in records
    )


def test_sam_summary_provider_reports_cache():
    sam_manager = SimpleNamespace(getCachedPredictorCount=lambda: 2)
    sam_delegate = SimpleNamespace(activePredictor=object())
    qpane = SimpleNamespace(
        samManager=lambda: sam_manager,
        masks=lambda: SimpleNamespace(sam_delegate=lambda: sam_delegate),
    )
    records = _sam_summary_diagnostics_provider(qpane)
    assert DiagnosticRecord("SAM|Cache", "2") in records
    assert DiagnosticRecord("SAM|State", "Ready") in records


def test_status_overlay_toggle(qapp):
    qpane = QPane(features=())
    qpane.show()
    qapp.processEvents()
    try:
        overlay = qpane.createStatusOverlay()
        assert overlay.isHidden()
        overlay.set_active(True)
        qapp.processEvents()
        assert overlay.isVisible()
        overlay.set_active(False)
        qapp.processEvents()
        assert overlay.isHidden()
    finally:
        overlay.deleteLater()
        qpane.deleteLater()
        qapp.processEvents()


def test_cache_diagnostics_provider_reports_usage(qapp):
    mb = 1024 * 1024
    qpane = QPane(features=())
    try:
        coordinator = qpane.cacheCoordinator
        assert coordinator is not None
        qpane.cacheCoordinator.set_active_budget(64 * mb)
        tile_manager = qpane.view().tile_manager
        tile_manager.cache_limit_bytes = 32 * mb
        tile_manager._cache_size_bytes = 8 * mb
        tile_manager._cache_hits = 5
        tile_manager._cache_misses = 2
        coordinator.update_usage("tiles", 8 * mb)
        qpane.diagnostics().set_domain_detail_enabled("cache", True)
        snapshot = qpane.gatherDiagnostics()
        rendered = snapshot.renderStrings()
        assert any(row.startswith("Cache:") for row in rendered)
        assert any(row.startswith("Cache|Tiles") for row in rendered)
    finally:
        qpane.deleteLater()
        qapp.processEvents()


def test_cache_diagnostics_orders_aggregate_and_marks_hard_mode(qapp):
    qpane = QPane(features=())
    try:
        qpane.applySettings(cache={"mode": "hard", "budget_mb": 2})
        rendered = qpane.gatherDiagnostics().renderStrings()
        cache_rows = [row for row in rendered if row.startswith("Cache:")]
        assert len(cache_rows) == 1
        assert "(hard)" in cache_rows[0]
    finally:
        qpane.deleteLater()
        qapp.processEvents()


def test_cache_diagnostics_provider_handles_snapshot_failure(qapp, caplog):
    qpane = QPane(features=())
    try:

        def _boom():
            raise RuntimeError("snapshot boom")

        qpane._state.cache_coordinator = SimpleNamespace(
            snapshot=_boom,
            active_budget_bytes=0,
            set_active_budget=lambda *args: None,
            set_headroom_snapshot=lambda *args: None,
        )
        caplog.set_level(logging.WARNING)
        detailed = tuple(cache_diagnostics_provider(qpane))
        detail_rows = tuple(cache_detail_provider(qpane))
        assert detailed == ()
        assert detail_rows == ()
        assert any("snapshot failed" in record.message for record in caplog.records)
    finally:
        qpane.deleteLater()
        qapp.processEvents()


def test_swap_progress_provider_compact(qapp):
    mb = 1024 * 1024
    qpane = QPane(features=())
    try:
        view = qpane.view()
        delegate = view.swap_delegate
        delegate.snapshot_metrics = lambda: SwapCoordinatorMetrics(
            pending_mask_prefetch=2,
            pending_predictors=1,
            pending_pyramid_prefetch=0,
            pending_tile_prefetch=0,
            last_navigation_ms=42.0,
        )

        class MaskStub:
            def snapshot_metrics(self):
                return SimpleNamespace(
                    cache_bytes=3 * mb,
                    hits=5,
                    misses=2,
                    colorize_last_ms=12.5,
                )

        qpane.mask_controller = MaskStub()
        tile_manager = view.tile_manager
        tile_manager._cache_size_bytes = 2 * mb
        tile_manager.cache_limit_bytes = 4 * mb
        tile_manager._cache_hits = 7
        tile_manager._cache_misses = 3
        pyramid_manager = qpane.catalog().pyramidManager()
        pyramid_manager._cache_size_bytes = 5 * mb
        pyramid_manager.cache_limit_bytes = 8 * mb
        qpane._set_sam_manager(
            SimpleNamespace(
                snapshot_metrics=lambda: SimpleNamespace(
                    cache_bytes=mb,
                    cache_count=1,
                    pending_retries=0,
                )
            )
        )
        records = tuple(swap_progress_provider(qpane))
        swap_rows = [record for record in records if record.label.startswith("Swap|")]
        assert len(swap_rows) <= 7
        assert all(record.label != "Swap|Summary" for record in swap_rows)
        assert any(record.label == "Swap|Renderer" for record in swap_rows)
        assert any(record.label == "Swap|Prefetch" for record in swap_rows)
    finally:
        qpane.deleteLater()
        qapp.processEvents()


def test_rendering_retry_provider_emits_rows(qapp):
    qpane = QPane(features=())
    try:
        tile_snapshot = RetrySnapshot(
            categories={
                "tiles": RetryCategorySnapshot(
                    active=2, total_scheduled=5, peak_active=3
                )
            }
        )
        pyramid_snapshot = RetrySnapshot(
            categories={
                "pyramid": RetryCategorySnapshot(
                    active=1, total_scheduled=4, peak_active=None
                )
            }
        )
        view = qpane.view()
        tile_manager = view.tile_manager
        pyramid_manager = qpane.catalog().pyramidManager()
        tile_manager.retry_snapshot = lambda: tile_snapshot  # type: ignore[assignment]
        pyramid_manager.retry_snapshot = lambda: pyramid_snapshot  # type: ignore[assignment]
        diagnostics = qpane.diagnostics()
        rows = qpane.gatherDiagnostics().rows()
        assert ("Retry|Tiles", "active=2 scheduled=5 peak=3") not in rows
        assert ("Retry|Pyramids", "active=1 scheduled=4") not in rows
        diagnostics.set_domain_detail_enabled("retry", True)
        rows = qpane.gatherDiagnostics().rows()
        assert ("Retry|Tiles", "active=2 scheduled=5 peak=3") in rows
        assert ("Retry|Pyramids", "active=1 scheduled=4") in rows
    finally:
        qpane.deleteLater()
        qapp.processEvents()


def test_overlay_formats_grouped_swap_rows(qapp):
    qpane = QPane(features=())
    overlay = qpane.createStatusOverlay()
    try:
        rows = (
            ("Swap|Summary", "nav=1ms"),
            ("Swap|Prefetch", "mask_prefetch=1"),
            ("Cache", "1/2 MB"),
        )
        formatted = overlay._format_rows(rows)
        lines = formatted.splitlines()
        swap_lines = [line for line in lines if line.startswith(("Swap", "    "))]
        assert swap_lines
        assert swap_lines[0].startswith("Swap")
        assert len(swap_lines) == 2
    finally:
        overlay.deleteLater()
        qpane.deleteLater()
        qapp.processEvents()


def test_detail_provider_gated_until_enabled(qapp):
    qpane = QPane(features=())
    try:
        qpane.hooks.register_diagnostics_provider(
            lambda _: (DiagnosticRecord("Detail", "enabled"),),
            domain="custom.detail",
            tier="detail",
        )
        snapshot = qpane.gatherDiagnostics()
        assert "Detail: enabled" not in snapshot.renderStrings()
        qpane.diagnostics().set_domain_detail_enabled("custom.detail", True)
        snapshot = qpane.gatherDiagnostics()
        assert "Detail: enabled" in snapshot.renderStrings()
    finally:
        qpane.deleteLater()
        qapp.processEvents()


def test_overlay_controller_reports_domains(qapp):
    qpane = QPane(features=())
    try:
        qpane.hooks.register_diagnostics_provider(
            lambda _: (DiagnosticRecord("Toggled", "1"),),
            domain="custom.detail",
            tier="detail",
        )
        controller = qpane.diagnosticsOverlayController()
        assert "custom.detail" in controller.domains()
        controller.setDomainEnabled("custom.detail", True)
        snapshot = qpane.gatherDiagnostics()
        assert "Toggled: 1" in snapshot.renderStrings()
    finally:
        qpane.deleteLater()
        qapp.processEvents()
