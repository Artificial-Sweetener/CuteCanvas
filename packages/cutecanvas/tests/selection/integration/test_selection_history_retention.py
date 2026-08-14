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

"""Tests for bounded selection chronology without full-document amplification."""

from __future__ import annotations

import uuid

import numpy as np

from cutecanvas.composition.edit_history import CompositionEditHistory
from cutecanvas.coverage import CoverageDocument, CoverageSnapshot, RasterCoverageItem
from cutecanvas.resources import ProjectResourceReference
from cutecanvas.scene.pixel_edits import RasterPixelEdit
from cutecanvas.selection import PixelSelectionEdit
from cutecanvas.types import RasterExtentPolicy
from qpane.sdk.scene import RasterBounds

_LARGE_EDGE = 2048
_TRANSITION_COUNT = 33


def _large_document(value: int) -> CoverageDocument:
    """Return one realistic immutable 2048-square selection document."""
    bounds = RasterBounds(0, 0, _LARGE_EDGE, _LARGE_EDGE)
    snapshot = CoverageSnapshot(
        bounds,
        RasterExtentPolicy.EXPAND_ON_WRITE,
        np.full((_LARGE_EDGE, _LARGE_EDGE), value, dtype=np.uint8),
    )
    return CoverageDocument().add(RasterCoverageItem(uuid.uuid4(), snapshot))


def test_large_selection_chronology_accounts_for_shared_revisions_once() -> None:
    """Adjacent 2048-square transitions retain each immutable revision once."""
    scene_id = uuid.uuid4()
    history = CompositionEditHistory()
    before = _large_document(1)

    for value in range(2, _TRANSITION_COUNT + 2):
        after = _large_document(value)
        history.record_applied(PixelSelectionEdit(scene_id, before, after))
        before = after

    expected_documents = _TRANSITION_COUNT + 1
    expected_bytes = expected_documents * _LARGE_EDGE * _LARGE_EDGE
    assert len(history.undo_commands(scene_id)) == _TRANSITION_COUNT
    assert history.retained_bytes(scene_id) == expected_bytes
    assert expected_bytes < 256 * 1024 * 1024


def test_large_delete_patch_does_not_retain_a_second_uncompressed_copy() -> None:
    """A 2048-square transparent result should use semantic patch retention."""
    rng = np.random.default_rng(1949)
    before = rng.integers(
        0,
        256,
        size=(_LARGE_EDGE, _LARGE_EDGE, 4),
        dtype=np.uint8,
    )
    after = np.zeros_like(before)
    edit = RasterPixelEdit(
        scene_id=uuid.uuid4(),
        layer_id=uuid.uuid4(),
        source=ProjectResourceReference(uuid.uuid4()),
        bounds=RasterBounds(0, 0, _LARGE_EDGE, _LARGE_EDGE),
        before=before,
        after=after,
    )

    assert edit.retained_bytes <= before.nbytes + 4096
