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

"""Stress coverage validating swap responsiveness under background contention."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import MethodType

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from qpane import Config, QPane, sam
from qpane.core.config_features import MaskConfigSlice
from qpane.features import FeatureInstallError
from qpane.masks.mask import MaskAssetStore
from qpane.masks.mask_controller import MaskController
from qpane.masks.mask_service import MaskService
from qpane.rendering import TileGeneratorWorker
from qpane.sam.manager import SamManager
from qpane.swap.diagnostics import swap_progress_provider

_WORKER_DELAY_SECONDS = 0.0005  # keep contention observable without long sleeps
_SWAPS_TO_STRESS = 2
_QPANE_EDGE_PX = 192  # smaller widget keeps Qt layout/setup minimal during fixture prep
_IMAGE_SIZE = 64  # compact canvases keep colorization+prefetch work fast


@dataclass(slots=True)
class SwapEnvironment:
    """Bundle swap orchestration dependencies for stress testing."""

    qpane: QPane
    mask_manager: MaskAssetStore
    mask_controller: MaskController
    mask_service: MaskService
    sam_manager: SamManager
    tmp_path: Path


def _make_image(color: Qt.GlobalColor) -> QImage:
    """Create an ARGB image filled with the requested colour."""
    image = QImage(_IMAGE_SIZE, _IMAGE_SIZE, QImage.Format_ARGB32)
    image.fill(color)
    return image


def _wait_for_executor(
    qpane: QPane,
    qapp: QApplication,
    *,
    timeout: float = 5.0,
    sleep_interval: float = 0.001,
) -> None:
    """Spin the Qt event loop until the qpane executor drains or timeout expires."""
    deadline = time.monotonic() + timeout
    executor = qpane.executor
    while time.monotonic() < deadline:
        qapp.processEvents()
        snapshot = executor.snapshot()
        if snapshot.active_total == 0 and snapshot.pending_total == 0:
            return
        time.sleep(sleep_interval)
    raise AssertionError("Executor did not drain within the allotted timeout")


def _first_prefetch_row(qpane: QPane) -> str:
    """Return the swap diagnostics prefetch row value when available."""
    for record in swap_progress_provider(qpane):
        if record.label == "Swap|Prefetch":
            return record.value
    return ""


def _parse_prefetch_counts(value: str) -> tuple[int | None, int | None]:
    """Extract mask and predictor counts from a diagnostics row."""
    mask_count: int | None = None
    predictor_count: int | None = None
    for part in value.split(" | "):
        if "=" not in part:
            continue
        key, raw = part.split("=", 1)
        try:
            count = int(raw)
        except ValueError:
            continue
        if key == "mask_prefetch":
            mask_count = count
        elif key == "predictors":
            predictor_count = count
    return mask_count, predictor_count


@pytest.fixture()
def swap_env(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> SwapEnvironment:
    """Provision a qpane with live mask and SAM services backed by the real executor."""
    qpane = QPane(features=())
    qpane.resize(_QPANE_EDGE_PX, _QPANE_EDGE_PX)
    base_config = Config()
    mask_config = MaskConfigSlice()
    mask_manager = MaskAssetStore(undo_limit=mask_config.mask_undo_limit)
    mask_controller = MaskController(
        mask_manager,
        source_to_panel_point=qpane.view().viewport.content_to_panel_point,
        config=base_config,
        mask_config=mask_config,
    )
    mask_service = MaskService(
        qpane=qpane,
        mask_assets=mask_manager,
        mask_controller=mask_controller,
        config=base_config,
        mask_config=mask_config,
        executor=qpane.executor,
    )
    qpane.attachMaskService(mask_service)

    class _Predictor:
        """Predictor stub that tracks the last image assignment."""

        def __init__(self) -> None:
            self.image: object | None = None
            self.model = None

        def set_image(self, image: object) -> None:
            """Capture the supplied image for later assertions."""
            self.image = image

    monkeypatch.setattr(
        sam.service,
        "load_predictor",
        lambda checkpoint_path, device="cpu": _Predictor(),
    )
    sam_manager = SamManager(
        executor=qpane.executor, checkpoint_path=Path("sam-checkpoint.pt")
    )
    qpane.attachSamManager(sam_manager)
    try:
        qpane.applySettings(cache={"prefetch": {"pyramids": 0, "tiles": 0}})
    except FeatureInstallError:
        # Some tests install mask services manually without the mask feature; skip.
        pass
    qapp.processEvents()
    try:
        yield SwapEnvironment(
            qpane=qpane,
            mask_manager=mask_manager,
            mask_controller=mask_controller,
            mask_service=mask_service,
            sam_manager=sam_manager,
            tmp_path=tmp_path,
        )
    finally:
        qpane.detachSamManager()
        _wait_for_executor(qpane, qapp)
        qpane.detachMaskService()
        qpane.deleteLater()
        qapp.processEvents()


@pytest.mark.usefixtures("qapp")
def test_swap_responsiveness_under_contention(
    swap_env: SwapEnvironment,
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drive rapid swaps under worker contention and assert diagnostics health."""
    qpane = swap_env.qpane
    mask_manager = swap_env.mask_manager
    mask_controller = swap_env.mask_controller
    mask_service = swap_env.mask_service
    sam_manager = swap_env.sam_manager
    tmp_path = swap_env.tmp_path
    original_tile_run = TileGeneratorWorker.run

    def _delayed_tile_run(self: TileGeneratorWorker) -> None:
        """Sleep briefly before delegating to the real tile worker."""
        time.sleep(_WORKER_DELAY_SECONDS)
        original_tile_run(self)

    monkeypatch.setattr(TileGeneratorWorker, "run", _delayed_tile_run)
    original_prepare = mask_controller.renders.prepare_image_detached

    def _delayed_prepare(
        self: object,
        mask_layer: object,
        *,
        mask_id: uuid.UUID | None = None,
    ) -> QImage | None:
        """Pause slightly to simulate heavy mask colorisation."""
        time.sleep(_WORKER_DELAY_SECONDS)
        return original_prepare(mask_layer, mask_id=mask_id)

    mask_controller.renders.prepare_image_detached = MethodType(
        _delayed_prepare,
        mask_controller.renders,
    )
    mask_prefetch_calls: list[tuple[uuid.UUID | None, str, bool]] = []
    mask_cancelled: list[uuid.UUID | None] = []
    predictor_cancelled: list[uuid.UUID] = []
    original_prefetch = mask_service.prefetchColorizedMasks

    def _recording_prefetch(
        self: MaskService,
        image_id: uuid.UUID | None,
        *,
        reason: str,
        scales: tuple[float, ...] | None = None,
    ) -> bool:
        """Capture mask prefetch scheduling while executing the real implementation."""
        result = original_prefetch(image_id, reason=reason, scales=scales)
        mask_prefetch_calls.append((image_id, reason, result))
        return result

    mask_service.prefetchColorizedMasks = MethodType(
        _recording_prefetch,
        mask_service,
    )
    original_cancel_prefetch = mask_service.cancelPrefetch

    def _recording_cancel(self: MaskService, image_id: uuid.UUID | None) -> bool:
        """Track prefetch cancellations and delegate to the real service."""
        mask_cancelled.append(image_id)
        return original_cancel_prefetch(image_id)

    mask_service.cancelPrefetch = MethodType(
        _recording_cancel,
        mask_service,
    )
    original_cancel_predictor = sam_manager.cancelPendingPredictor

    def _recording_predictor_cancel(self: SamManager, image_id: uuid.UUID) -> bool:
        """Log predictor cancellations for assertions while cancelling as usual."""
        predictor_cancelled.append(image_id)
        return original_cancel_predictor(image_id)

    sam_manager.cancelPendingPredictor = MethodType(
        _recording_predictor_cancel,
        sam_manager,
    )
    colors = (Qt.red, Qt.blue, Qt.green, Qt.yellow)
    image_ids: list[uuid.UUID] = []
    images: list[QImage] = []
    paths: list[Path] = []
    for index, color in enumerate(colors):
        image_ids.append(uuid.uuid4())
        image = _make_image(color)
        path = tmp_path / f"swap-{index}.png"
        path.touch()  # placeholder file avoids expensive PNG writes during setup
        images.append(image)
        paths.append(path)
    image_map = QPane.imageMapFromLists(images=images, paths=paths, ids=image_ids)
    qpane.setImagesByID(image_map, image_ids[0])
    qapp.processEvents()
    mask_ids: list[uuid.UUID] = []
    for image_id, image in zip(image_ids, images, strict=True):
        mask_id = mask_manager.create_mask(image)
        layer = mask_manager.get_layer(mask_id)
        assert layer is not None
        layer.surface.fill(64 + len(mask_ids) * 32)
        assert mask_service.layers.attach(
            mask_id,
            image_id,
            color=QColor(255, 0, 0),
            opacity=0.5,
        )
        mask_ids.append(mask_id)
    mask_controller.setActiveMaskID(mask_ids[0])
    mask_service.ensureTopMaskActiveForImage(image_ids[0])
    qapp.processEvents()
    qpane.setCurrentImageID(image_ids[0])
    qapp.processEvents()
    _wait_for_executor(qpane, qapp)
    qpane.view().viewport.setZoomFit()
    qapp.processEvents()
    observed_prefetch_rows: list[str] = []
    colorize_sources_seen: set[str] = set()
    observed_pending_during_stress = False
    for iteration in range(_SWAPS_TO_STRESS):
        target_id = image_ids[(iteration + 1) % len(image_ids)]
        qpane.setCurrentImageID(target_id)
        qapp.processEvents()
        time.sleep(_WORKER_DELAY_SECONDS)
        qapp.processEvents()
        row_value = _first_prefetch_row(qpane)
        if row_value:
            observed_prefetch_rows.append(row_value)
            masks, predictors = _parse_prefetch_counts(row_value)
            if (masks and masks > 0) or (predictors and predictors > 0):
                observed_pending_during_stress = True
        mask_snapshot = mask_controller.renders.snapshot_metrics()
        last_source = getattr(mask_snapshot, "colorize_last_source", None)
        if last_source:
            colorize_sources_seen.add(last_source)
    intermediate_metrics = qpane.view().swap_delegate.snapshot_metrics()
    assert intermediate_metrics.pending_mask_prefetch >= 0
    assert intermediate_metrics.pending_predictors >= 0
    assert observed_prefetch_rows, "Expected diagnostics rows during stress"
    assert (
        observed_pending_during_stress
    ), "Expected in-flight work during navigation burst"
    _wait_for_executor(qpane, qapp)
    qapp.processEvents()
    final_metrics = qpane.view().swap_delegate.snapshot_metrics()
    snapshot_after = mask_controller.renders.snapshot_metrics()
    last_source_after = getattr(snapshot_after, "colorize_last_source", None)
    if last_source_after:
        colorize_sources_seen.add(last_source_after)
    mask_metrics = snapshot_after
    sam_metrics = sam_manager.snapshot_metrics()
    assert final_metrics.pending_mask_prefetch <= len(image_ids)
    assert final_metrics.pending_predictors <= len(image_ids)
    assert colorize_sources_seen, "Expected mask colorize activity during swaps"
    assert "prefetch" in colorize_sources_seen
    if "snippet_provisional" in colorize_sources_seen:
        assert "snippet" in colorize_sources_seen
    assert (
        mask_metrics.prefetch_requested
        == mask_metrics.prefetch_completed + mask_metrics.prefetch_failed
    )
    assert mask_metrics.prefetch_completed > 0
    assert sam_metrics.active_jobs == 0
    assert sam_metrics.pending_retries == 0
    prefetch_after = _first_prefetch_row(qpane)
    masks_after, predictors_after = _parse_prefetch_counts(prefetch_after)
    assert masks_after == final_metrics.pending_mask_prefetch
    assert predictors_after == final_metrics.pending_predictors
    assert mask_prefetch_calls, "Mask prefetch should be scheduled during stress"
    assert any(image_id is not None for image_id, _, _ in mask_prefetch_calls)
    assert any(image_id is not None for image_id in mask_cancelled)
    assert predictor_cancelled, "Predictor cancellations should occur for stale work"


def test_parse_prefetch_counts_handles_missing_fields() -> None:
    """Ensure diagnostics parsing tolerates absent counters."""
    masks, predictors = _parse_prefetch_counts("mask_prefetch=2 | tiles=4")
    assert masks == 2
    assert predictors is None
    masks, predictors = _parse_prefetch_counts("predictors=3")
    assert masks is None
    assert predictors == 3
