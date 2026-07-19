#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Tests for composition-scoped pixel-selection state."""

from __future__ import annotations

import random
import uuid

import numpy as np

from qpane.coverage import CoverageCombineMode, CoverageSnapshot
from qpane.scene.raster import RasterBounds, RasterExtentPolicy
from qpane.selection import PixelSelectionService


def _snapshot(x: int, y: int, pixels: list[list[int]]) -> CoverageSnapshot:
    array = np.asarray(pixels, dtype=np.uint8)
    return CoverageSnapshot(
        bounds=RasterBounds(x, y, array.shape[1], array.shape[0]),
        extent_policy=RasterExtentPolicy.EXPAND_ON_WRITE,
        pixels=array,
    )


def test_selection_state_is_isolated_by_scene() -> None:
    first_scene = uuid.uuid4()
    second_scene = uuid.uuid4()
    service = PixelSelectionService()

    assert service.commit(first_scene, _snapshot(4, 7, [[255]]))

    assert service.state(first_scene).has_selection
    assert not service.state(second_scene).has_selection
    assert service.state(first_scene).revision == 1
    assert service.state(second_scene).revision == 0


def test_selection_combination_is_coordinate_aware_and_soft() -> None:
    scene_id = uuid.uuid4()
    service = PixelSelectionService()
    service.commit(scene_id, _snapshot(1, 1, [[255, 128], [64, 0]]))

    assert service.commit(
        scene_id,
        _snapshot(2, 1, [[128, 255], [255, 255]]),
        CoverageCombineMode.ADD,
    )

    state = service.state(scene_id)
    assert state.coverage is not None
    assert state.coverage.bounds == RasterBounds(1, 1, 3, 2)
    assert state.coverage.pixels.tolist() == [[255, 192, 255], [64, 255, 255]]


def test_subtract_and_intersect_trim_empty_outer_storage() -> None:
    scene_id = uuid.uuid4()
    service = PixelSelectionService()
    service.commit(scene_id, _snapshot(10, 20, [[255, 255, 255]]))

    service.commit(
        scene_id,
        _snapshot(10, 20, [[255, 0, 255]]),
        CoverageCombineMode.SUBTRACT,
    )

    state = service.state(scene_id)
    assert state.coverage is not None
    assert state.coverage.bounds == RasterBounds(11, 20, 1, 1)
    assert state.coverage.pixels.tolist() == [[255]]

    service.commit(
        scene_id,
        _snapshot(0, 0, [[255]]),
        CoverageCombineMode.INTERSECT,
    )
    assert not service.state(scene_id).has_selection


def test_identical_commit_is_a_revision_noop() -> None:
    scene_id = uuid.uuid4()
    service = PixelSelectionService()
    snapshot = _snapshot(2, 3, [[0, 128, 0]])

    assert service.commit(scene_id, snapshot)
    assert not service.commit(scene_id, snapshot)
    assert service.state(scene_id).revision == 1


def test_select_all_and_invert_use_finite_scene_bounds() -> None:
    scene_id = uuid.uuid4()
    service = PixelSelectionService()
    bounds = RasterBounds(-2, 5, 3, 2)

    assert service.select_all(scene_id, bounds)
    selected = service.state(scene_id).coverage
    assert selected is not None
    assert np.all(selected.pixels == 255)

    assert service.invert(scene_id, bounds)
    assert not service.state(scene_id).has_selection


def test_changed_observer_receives_immutable_current_state() -> None:
    scene_id = uuid.uuid4()
    observed = []
    service = PixelSelectionService(observed.append)

    service.commit(scene_id, _snapshot(0, 0, [[255]]))
    service.clear(scene_id)

    assert [state.revision for state in observed] == [1, 2]
    assert observed[0].has_selection
    assert not observed[1].has_selection


def test_selection_records_edits_and_restore_does_not_record() -> None:
    scene_id = uuid.uuid4()
    edits = []
    service = PixelSelectionService(record_edit=edits.append)

    service.commit(scene_id, _snapshot(0, 0, [[64, 255]]))
    assert len(edits) == 1
    assert edits[0].before is None
    assert edits[0].after is not None

    assert service.restore(scene_id, edits[0].before)
    assert len(edits) == 1
    assert not service.state(scene_id).has_selection


def test_randomized_selection_algebra_matches_independent_finite_canvas_oracle() -> (
    None
):
    """Hostile offset and mode sequences must preserve exact soft coverage algebra."""
    origin = -24
    size = 64
    modes = tuple(CoverageCombineMode)
    for seed in range(48):
        randomizer = random.Random(seed)
        scene_id = uuid.uuid4()
        service = PixelSelectionService()
        expected = np.zeros((size, size), dtype=np.uint8)
        for _step in range(32):
            width = randomizer.randint(1, 12)
            height = randomizer.randint(1, 12)
            x = randomizer.randint(-20, 20)
            y = randomizer.randint(-20, 20)
            incoming = np.asarray(
                [
                    [randomizer.randrange(256) for _column in range(width)]
                    for _row in range(height)
                ],
                dtype=np.uint8,
            )
            mode = randomizer.choice(modes)
            service.commit(scene_id, _snapshot(x, y, incoming.tolist()), mode)

            source = np.zeros_like(expected)
            source[
                y - origin : y - origin + height,
                x - origin : x - origin + width,
            ] = incoming
            destination = expected.astype(np.uint32)
            source_wide = source.astype(np.uint32)
            if mode is CoverageCombineMode.REPLACE or not np.any(expected):
                expected = source
            elif mode is CoverageCombineMode.ADD:
                expected = (
                    source_wide + (destination * (255 - source_wide) + 127) // 255
                ).astype(np.uint8)
            elif mode is CoverageCombineMode.SUBTRACT:
                expected = ((destination * (255 - source_wide) + 127) // 255).astype(
                    np.uint8
                )
            else:
                expected = ((destination * source_wide + 127) // 255).astype(np.uint8)

            occupied = np.argwhere(expected != 0)
            state = service.state(scene_id)
            if occupied.size == 0:
                assert not state.has_selection
                continue
            top, left = occupied.min(axis=0)
            bottom, right = occupied.max(axis=0) + 1
            assert state.coverage is not None
            assert state.coverage.bounds == RasterBounds(
                origin + int(left),
                origin + int(top),
                int(right - left),
                int(bottom - top),
            )
            assert np.array_equal(
                state.coverage.pixels,
                expected[top:bottom, left:right],
            )
