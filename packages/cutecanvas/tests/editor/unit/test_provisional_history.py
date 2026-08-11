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
"""Bounded provisional history independent-oracle and invalid-input proof."""

from __future__ import annotations

import random
from typing import cast

import pytest
from cutecanvas.editor.provisional_history import BoundedProvisionalHistory


@pytest.mark.parametrize("limit", [-1, 0, 4097, True, 1.5])
def test_history_rejects_unsafe_checkpoint_limits(limit: object) -> None:
    """Reject capacities that cannot provide the documented memory bound."""
    with pytest.raises(ValueError, match="checkpoint_limit"):
        BoundedProvisionalHistory(0, checkpoint_limit=cast(int, limit))


def test_history_preserves_base_while_bounding_intermediate_values() -> None:
    """Keep the exact base reachable after old intermediate checkpoints expire."""
    history = BoundedProvisionalHistory("base", checkpoint_limit=3)
    for value in ("one", "two", "three", "four", "five"):
        assert history.push(value, f"Set {value}")

    assert history.snapshot.undo_depth == 3
    assert history.undo() == "four"
    assert history.undo() == "three"
    assert history.undo() == "base"
    assert history.undo() is None


def test_history_discards_redo_after_a_distinct_branch() -> None:
    """Replace abandoned future checkpoints after editing an undone state."""
    history = BoundedProvisionalHistory(0, checkpoint_limit=8)
    assert history.push(1, "One")
    assert history.push(2, "Two")
    assert history.undo() == 1
    assert history.push(3, "Three")

    assert history.current == 3
    assert not history.snapshot.can_redo
    assert history.redo() is None


def test_history_ignores_no_op_values_and_rejects_empty_labels() -> None:
    """Create checkpoints only for truthful, labelled semantic transitions."""
    history = BoundedProvisionalHistory(0, checkpoint_limit=8)
    assert not history.push(0, "No change")
    with pytest.raises(ValueError, match="label"):
        history.push(1, "  ")
    assert history.snapshot.undo_depth == 0


def test_history_matches_an_independent_cursor_oracle() -> None:
    """Match a direct list-and-cursor model through deterministic random actions."""
    randomizer = random.Random(912_441)
    limit = 7
    history = BoundedProvisionalHistory(0, checkpoint_limit=limit)
    oracle = [0]
    cursor = 0
    next_value = 1

    for _step in range(500):
        action = randomizer.choice(("push", "undo", "redo"))
        if action == "push":
            value = next_value
            next_value += 1
            assert history.push(value, f"Value {value}")
            del oracle[cursor + 1 :]
            oracle.append(value)
            cursor = len(oracle) - 1
            if len(oracle) - 1 > limit:
                del oracle[1]
                cursor -= 1
        elif action == "undo":
            expected = None
            if cursor > 0:
                cursor -= 1
                expected = oracle[cursor]
            assert history.undo() == expected
        else:
            expected = None
            if cursor + 1 < len(oracle):
                cursor += 1
                expected = oracle[cursor]
            assert history.redo() == expected
        assert history.current == oracle[cursor]
        assert history.snapshot.undo_depth == cursor
        assert history.snapshot.redo_depth == len(oracle) - cursor - 1
