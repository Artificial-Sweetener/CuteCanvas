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
"""Normalized inspection projection and coordination contracts."""

from __future__ import annotations

import uuid
from math import isclose

import pytest
from PySide6.QtCore import QPointF, QRectF, QSizeF
from qpane import (
    InspectionRegion,
    InspectionStateStore,
    InspectionTarget,
    InspectionViewState,
    InspectionZoomMode,
    LinkedGroup,
    capture_inspection,
    project_inspection,
)


def _target(width: float, height: float) -> InspectionTarget:
    """Create one origin-aligned inspection target."""
    return InspectionTarget(uuid.uuid4(), QRectF(0.0, 0.0, width, height))


def test_projection_preserves_native_zoom_semantics_across_resolutions() -> None:
    """One semantic region derives different local zoom for each resolution."""
    low = _target(1000.0, 1000.0)
    high = _target(2000.0, 2000.0)
    viewport = QSizeF(500.0, 500.0)
    state = capture_inspection(
        low,
        viewport,
        zoom=2.0,
        pan=QPointF(-100.0, 50.0),
    )

    low_projection = project_inspection(low, viewport, state)
    high_projection = project_inspection(high, viewport, state)

    assert isclose(low_projection.zoom, 2.0)
    assert low_projection.pan == QPointF(-100.0, 50.0)
    assert isclose(high_projection.zoom, 1.0)
    assert high_projection.pan == QPointF(-100.0, 50.0)


def test_projection_contains_region_when_target_aspect_changes() -> None:
    """Aspect changes show the complete normalized region without cropping."""
    wide = _target(2000.0, 1000.0)
    square = _target(1000.0, 1000.0)
    viewport = QSizeF(800.0, 600.0)
    state = capture_inspection(
        wide,
        viewport,
        zoom=1.0,
        pan=QPointF(),
    )

    projected = project_inspection(square, viewport, state)

    horizontal_zoom = viewport.width() / (square.bounds.width() * state.region.span_x)
    vertical_zoom = viewport.height() / (square.bounds.height() * state.region.span_y)
    assert projected.zoom == min(horizontal_zoom, vertical_zoom)


def test_linked_one_to_one_is_local_while_fit_is_shared() -> None:
    """One-to-one belongs to its source target while fit remains intentional."""
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()
    store = InspectionStateStore()
    store.replace_groups((LinkedGroup(uuid.uuid4(), (first_id, second_id)),))
    region = InspectionRegion(0.5, 0.5, 0.25, 0.25)

    store.update(
        first_id,
        InspectionViewState(region, InspectionZoomMode.ONE_TO_ONE),
    )

    assert store.state_for(first_id) == InspectionViewState(
        region,
        InspectionZoomMode.ONE_TO_ONE,
    )
    assert store.state_for(second_id) == InspectionViewState(
        region,
        InspectionZoomMode.CUSTOM,
    )

    store.update(
        second_id,
        InspectionViewState(region, InspectionZoomMode.FIT),
    )

    assert store.state_for(first_id) == InspectionViewState(
        region,
        InspectionZoomMode.FIT,
    )


def test_linked_updates_notify_views_once_and_ignore_reentrant_publish() -> None:
    """Applying a linked update cannot recursively bounce between viewports."""
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()
    store = InspectionStateStore()
    store.replace_groups((LinkedGroup(uuid.uuid4(), (first_id, second_id)),))
    updates: list[tuple[uuid.UUID, int]] = []
    region = InspectionRegion(0.4, 0.6, 0.5, 0.5)

    def receive(update) -> None:
        """Record delivery and simulate a viewport change callback."""
        updates.append((update.target_id, update.generation))
        store.update(update.target_id, update.state)

    store.subscribe(first_id, receive)
    store.subscribe(second_id, receive)

    generation = store.update(
        first_id,
        InspectionViewState(region),
    )

    assert generation == 1
    assert updates == [(first_id, 1), (second_id, 1)]
    assert store.generation == 1


def test_group_validation_and_target_removal_are_atomic() -> None:
    """Invalid overlap cannot mutate valid group membership."""
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()
    third_id = uuid.uuid4()
    original = LinkedGroup(uuid.uuid4(), (first_id, second_id))
    store = InspectionStateStore()
    store.replace_groups((original,))

    with pytest.raises(ValueError):
        store.replace_groups(
            (
                original,
                LinkedGroup(uuid.uuid4(), (second_id, third_id)),
            )
        )

    assert store.groups() == (original,)
    store.discard(first_id)
    assert store.groups() == ()
