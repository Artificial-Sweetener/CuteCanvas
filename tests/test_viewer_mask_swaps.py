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

"""Latency regression tests for mask overlay swaps."""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from statistics import mean

import pytest
from cutecanvas import CuteCanvas
from cutecanvas.masks.mask import MaskAssetStore
from cutecanvas.masks.mask_controller import MaskController
from cutecanvas.masks.mask_service import MaskService
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage

from tests.helpers.executor_stubs import StubExecutor

WARM_SWAP_THRESHOLD_MS = 120.0
_IMAGE_EDGE_PX = 192  # keep swaps representative without colorizing 4K overlays
_SWAP_SAMPLES = 2  # enough samples for smoothing without long runtimes
MaskPresence = tuple[bool, bool]


def _make_image(width: int, height: int, color: Qt.GlobalColor) -> QImage:
    """Return an ARGB32 image filled with ``color``."""
    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(color)
    return image


def _drain_executor(executor: StubExecutor) -> None:
    """Exhaust all pending work queued on ``executor``."""
    while True:
        pending = list(executor.pending_tasks())
        if not pending:
            break
        executor.drain_all()


def _measure_swap(
    qpane: CuteCanvas,
    image_id: uuid.UUID,
    *,
    qapp,
    samples: int = 3,
) -> float:
    """Return average swap duration for repeated navigation."""
    durations: list[float] = []
    for _ in range(max(1, samples)):
        qapp.processEvents()
        start_ns = time.perf_counter_ns()
        qpane.setCurrentImageID(image_id)
        qapp.processEvents()
        durations.append((time.perf_counter_ns() - start_ns) / 1_000_000.0)
    return mean(durations)


@contextmanager
def _mask_swap_environment(
    qapp, monkeypatch, *, mask_presence: MaskPresence
) -> Iterator[tuple[CuteCanvas, StubExecutor, tuple[uuid.UUID, uuid.UUID]]]:
    """Yield a qpane and executor configured according to ``mask_presence``."""
    from cutecanvas.masks import install as mask

    executor = StubExecutor()
    manager_box: dict[str, MaskAssetStore] = {}
    controller_box: dict[str, MaskController] = {}

    def install_mask_feature(qpane: CuteCanvas) -> None:
        mask_manager = MaskAssetStore(undo_limit=qpane.settings.mask_undo_limit)
        controller = MaskController(
            mask_manager,
            source_to_panel_point=lambda pt: pt,
            config=qpane.settings,
        )
        service = MaskService(
            qpane=qpane,
            mask_assets=mask_manager,
            mask_controller=controller,
            config=qpane.settings,
            executor=qpane.executor,
        )
        qpane.attachMaskService(service)
        qpane.refreshMaskAutosavePolicy()
        prefetch_spy: list[tuple[uuid.UUID, str]] = []
        original_prefetch = service.prefetchColorizedMasks

        def _recording_prefetch(image_id, *, reason, scales=None):
            prefetch_spy.append((image_id, reason))
            return original_prefetch(image_id, reason=reason, scales=scales)

        service.prefetchColorizedMasks = _recording_prefetch
        qpane._prefetch_spy = prefetch_spy
        manager_box["manager"] = mask_manager
        controller_box["controller"] = controller

    monkeypatch.setattr(mask, "install_mask_feature", install_mask_feature)
    qpane = CuteCanvas(features=("mask",), task_executor=executor)
    assert qpane.swapDelegate is not None
    qpane.resize(512, 512)
    try:
        mask_service = qpane.mask_service
        manager = manager_box["manager"]
        controller = controller_box["controller"]
        first_id = uuid.uuid4()
        second_id = uuid.uuid4()
        first_image = _make_image(_IMAGE_EDGE_PX, _IMAGE_EDGE_PX, Qt.white)
        second_image = _make_image(_IMAGE_EDGE_PX, _IMAGE_EDGE_PX, Qt.black)
        image_map = CuteCanvas.imageMapFromLists(
            images=[first_image, second_image],
            paths=[None, None],
            ids=[first_id, second_id],
        )
        qpane.setImagesByID(image_map, first_id)
        mask_config = (
            (first_id, first_image, mask_presence[0], 192),
            (second_id, second_image, mask_presence[1], 96),
        )
        mask_pairs: list[tuple[uuid.UUID, uuid.UUID | None]] = []
        for image_id, image, has_mask, fill_value in mask_config:
            if has_mask:
                mask_id = manager.create_mask(image)
                layer = manager.get_layer(mask_id)
                assert layer is not None
                layer.coverage.raster.fill(fill_value)
                assert mask_service.layers.attach(
                    mask_id,
                    image_id,
                    color=QColor(255, 0, 0),
                    opacity=0.5,
                )
                mask_pairs.append((image_id, mask_id))
            else:
                mask_pairs.append((image_id, None))
        active_mask_id = next(
            (mask_id for _, mask_id in mask_pairs if mask_id is not None), None
        )
        if active_mask_id is not None:
            controller.setActiveMaskID(active_mask_id)
        for image_id, mask_id in mask_pairs:
            if mask_id is not None:
                mask_service.ensureTopMaskActiveForImage(image_id)
        for image_id, mask_id in mask_pairs:
            prefetch_result = qpane.prefetchMaskOverlays(
                image_id, reason="test_prefetch"
            )
            if mask_id is not None:
                assert prefetch_result is True
                _drain_executor(executor)
            else:
                assert prefetch_result is False
        yield qpane, executor, (first_id, second_id)
    finally:
        qpane.deleteLater()
        qapp.processEvents()


@pytest.fixture
def mask_swap_environment(
    qapp, monkeypatch, request
) -> Iterator[tuple[CuteCanvas, StubExecutor, tuple[uuid.UUID, uuid.UUID]]]:
    """Provide warmed overlays for the requested mask presence setup."""
    mask_presence = getattr(request, "param", (True, True))
    if len(mask_presence) != 2:
        raise ValueError("mask_presence must describe exactly two images")
    with _mask_swap_environment(
        qapp,
        monkeypatch,
        mask_presence=tuple(bool(flag) for flag in mask_presence),
    ) as env:
        yield env


def _exercise_and_assert_swaps(
    qpane: CuteCanvas,
    executor: StubExecutor,
    image_ids: tuple[uuid.UUID, uuid.UUID],
    *,
    qapp,
    require_cache_hit: bool = True,
) -> tuple[float, float]:
    """Measure swaps in both directions and enforce the warm latency budget."""
    first_id, second_id = image_ids
    controller = qpane.mask_service.controller
    baseline = controller.renders.snapshot_metrics()
    prefetch_before = len(getattr(qpane, "_prefetch_spy", []))
    forward = _measure_swap(qpane, second_id, qapp=qapp, samples=_SWAP_SAMPLES)
    prefetch_after = len(getattr(qpane, "_prefetch_spy", []))
    assert prefetch_after > prefetch_before
    _drain_executor(executor)
    backward = _measure_swap(qpane, first_id, qapp=qapp, samples=_SWAP_SAMPLES)
    _drain_executor(executor)
    assert forward < WARM_SWAP_THRESHOLD_MS
    assert backward < WARM_SWAP_THRESHOLD_MS
    metrics = controller.renders.snapshot_metrics()
    if require_cache_hit:
        assert metrics.hits >= baseline.hits + 1
    else:
        assert metrics.hits >= baseline.hits
    assert metrics.misses <= baseline.misses + 2
    assert metrics.colorize_slow_count <= baseline.colorize_slow_count + 2
    assert metrics.colorize_last_source != "cache_miss"
    assert (metrics.colorize_last_ms or 0.0) < WARM_SWAP_THRESHOLD_MS
    return forward, backward


@pytest.mark.parametrize(
    "mask_swap_environment",
    [(False, True)],
    indirect=True,
)
def test_maskless_to_mask_swaps_remain_fast(mask_swap_environment, qapp) -> None:
    """Ensure maskless to masked swaps stay within the warm target."""
    qpane, executor, image_ids = mask_swap_environment
    forward, backward = _exercise_and_assert_swaps(
        qpane,
        executor,
        image_ids,
        qapp=qapp,
        require_cache_hit=False,
    )
    assert forward >= 0.0
    assert backward >= 0.0
