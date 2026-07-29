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
"""Verify source-neutral responsive layout and physical-pixel stability."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSizeF
from qpane.sdk.layout import (
    IncompleteRowAlignment,
    ResponsiveGridLayout,
    ResponsiveGridPacking,
    ResponsiveGridPolicy,
    ResponsiveGridTopology,
    TargetComparisonLayout,
    ViewTargetSpec,
)
from qpane.sdk.types import ComparisonOrientation


def _targets(count: int) -> tuple[ViewTargetSpec, ...]:
    """Return alternating landscape and portrait layout targets."""
    return tuple(
        ViewTargetSpec(
            f"target-{index}",
            QSizeF(1600.0, 900.0) if index % 2 == 0 else QSizeF(900.0, 1600.0),
        )
        for index in range(count)
    )


def test_grid_partitions_every_physical_pixel_without_rounding_drift() -> None:
    """Keep the final edge exact at fractional DPR and logical dimensions."""
    snapshot = ResponsiveGridLayout(
        ResponsiveGridPolicy(
            minimum_cell_width=300.0,
            gap=7.0,
            topology=ResponsiveGridTopology.MINIMUM_CELL_WIDTH,
        )
    ).arrange(
        QRectF(13.25, 19.5, 1000.4, 701.2),
        _targets(6),
        device_pixel_ratio=1.5,
    )

    assert snapshot.columns == 3
    assert snapshot.rows == 2
    assert math.isclose(
        max(frame.cell.right() for frame in snapshot.frames),
        13.25 + round(1000.4 * 1.5) / 1.5,
    )
    assert math.isclose(
        max(frame.cell.bottom() for frame in snapshot.frames),
        19.5 + round(701.2 * 1.5) / 1.5,
    )
    assert all(frame.cell.contains(frame.content) for frame in snapshot.frames)


def test_grid_hit_testing_visibility_and_prefetch_are_target_stable() -> None:
    """Resolve subjects and visible work from immutable target identities."""
    layout = ResponsiveGridLayout(
        ResponsiveGridPolicy(minimum_cell_width=250.0, gap=8.0)
    )
    snapshot = layout.arrange(QRectF(0.0, 0.0, 820.0, 600.0), _targets(6))
    frame = snapshot.frames[4]

    assert snapshot.hit_test(frame.cell.center()) == frame.target_id
    assert snapshot.hit_test(QPointF(-10.0, -10.0)) is None
    clip = QRectF(frame.cell)
    assert frame.target_id in snapshot.visible_target_ids(clip)
    assert set(snapshot.prefetch_order(clip)) == set(snapshot.visible_target_ids(clip))


def test_grid_damage_only_contains_removed_or_changed_cells() -> None:
    """Avoid repainting unchanged cells after a target-list mutation."""
    layout = ResponsiveGridLayout(
        ResponsiveGridPolicy(
            minimum_cell_width=300.0,
            gap=8.0,
            maximum_columns=3,
            topology=ResponsiveGridTopology.MINIMUM_CELL_WIDTH,
            incomplete_row_alignment=IncompleteRowAlignment.LEADING,
        )
    )
    before = layout.arrange(QRectF(0.0, 0.0, 1000.0, 600.0), _targets(5))
    after = layout.arrange(QRectF(0.0, 0.0, 1000.0, 600.0), _targets(4))
    damage = after.damage_from(before)

    assert damage == (before.frames[4].cell,)


def test_maximum_reference_area_topology_retains_then_releases_previous_shape() -> None:
    """Maximum-area topology uses the prior snapshot to avoid resize chatter."""
    layout = ResponsiveGridLayout(
        ResponsiveGridPolicy(
            topology_hysteresis_ratio=1.02,
        )
    )
    targets = tuple(
        ViewTargetSpec(f"target-{index}", QSizeF(512.0, 512.0)) for index in range(2)
    )
    previous = layout.arrange(QRectF(0.0, 0.0, 1000.0, 1000.0), targets)
    near = layout.arrange(
        QRectF(0.0, 0.0, 1009.0, 1000.0),
        targets,
        previous=previous,
    )
    far = layout.arrange(
        QRectF(0.0, 0.0, 1400.0, 1000.0),
        targets,
        previous=near,
    )

    assert previous.columns == 1
    assert near.columns == 1
    assert near.retained_previous_topology
    assert far.columns == 2
    assert not far.retained_previous_topology


def test_centered_incomplete_row_uses_exact_physical_cell_geometry() -> None:
    """Centered partial rows keep each target cell aligned to physical pixels."""
    snapshot = ResponsiveGridLayout(
        ResponsiveGridPolicy(
            maximum_columns=3,
            topology=ResponsiveGridTopology.MINIMUM_CELL_WIDTH,
            incomplete_row_alignment=IncompleteRowAlignment.CENTER,
        )
    ).arrange(QRectF(0.0, 0.0, 901.0, 600.0), _targets(5))

    final_row = snapshot.frames[3:]
    assert snapshot.columns == 3
    assert final_row[0].cell.x() == 151.0
    assert final_row[1].cell.x() == 454.0
    assert final_row[-1].cell.right() <= snapshot.viewport.right()


def test_native_tile_packing_preserves_compact_gutters_and_centered_final_row() -> None:
    """Pack portrait targets by native aspect instead of stretching grid cells."""
    targets = tuple(
        ViewTargetSpec(f"target-{index}", QSizeF(100.0, 140.0)) for index in range(3)
    )
    snapshot = ResponsiveGridLayout(
        ResponsiveGridPolicy(
            packing=ResponsiveGridPacking.NATIVE_TILES,
            native_tile_gap_ratio=1.0 / 512.0,
            native_tile_minimum_gap=2.0,
        )
    ).arrange(QRectF(0.0, 0.0, 1000.0, 1000.0), targets)

    first, second, final = snapshot.frames
    assert (snapshot.columns, snapshot.rows) == (2, 2)
    assert math.isclose(
        second.cell.x() - first.cell.right(), 2.0 * first.cell.width() / 100.0
    )
    assert math.isclose(final.cell.center().x(), snapshot.viewport.center().x())
    assert first.cell == first.content
    assert second.cell == second.content
    assert final.cell == final.content


def test_native_tile_gutter_uses_the_dominant_scene_axis() -> None:
    """Preserve the legacy gutter ratio when rows outnumber columns."""
    targets = tuple(
        ViewTargetSpec(f"target-{index}", QSizeF(3000.0, 2000.0)) for index in range(5)
    )
    snapshot = ResponsiveGridLayout(
        ResponsiveGridPolicy(
            packing=ResponsiveGridPacking.NATIVE_TILES,
            native_tile_gap_ratio=1.0 / 512.0,
        )
    ).arrange(QRectF(0.0, 0.0, 6000.0, 10000.0), targets)

    first, second = snapshot.frames[:2]
    displayed_gap = second.cell.x() - first.cell.right()

    assert (snapshot.columns, snapshot.rows) == (2, 3)
    assert math.isclose(displayed_gap / first.cell.width(), 2.0 / 511.0)


def test_native_tiles_keep_fixed_viewport_gutters_and_equal_target_sizes() -> None:
    """Keep equal images aligned while a width-constrained grid resizes."""

    targets = tuple(
        ViewTargetSpec(f"target-{index}", QSizeF(960.0, 1344.0)) for index in range(3)
    )
    layout = ResponsiveGridLayout(
        ResponsiveGridPolicy(
            packing=ResponsiveGridPacking.NATIVE_TILES,
            native_tile_viewport_gap=2.0,
        )
    )

    for width in range(1500, 1511):
        snapshot = layout.arrange(QRectF(0.0, 0.0, float(width), 1000.0), targets)
        first, second, final = snapshot.frames

        assert (snapshot.columns, snapshot.rows) == (3, 1)
        assert first.cell.width() == second.cell.width() == final.cell.width()
        assert first.cell.height() == second.cell.height() == final.cell.height()
        assert second.cell.x() - first.cell.right() == 2.0
        assert final.cell.x() - second.cell.right() == 2.0


def test_comparison_clips_share_one_exact_physical_boundary() -> None:
    """Prevent gaps and overlap at a fractional-DPR comparison divider."""
    viewport = QRectF(5.25, 8.5, 901.4, 507.3)
    snapshot = TargetComparisonLayout().arrange(
        viewport,
        split_position=0.371,
        orientation=ComparisonOrientation.VERTICAL,
        device_pixel_ratio=1.5,
    )

    assert snapshot.primary_clip.right() == snapshot.secondary_clip.left()
    assert math.isclose(
        snapshot.primary_clip.width() + snapshot.secondary_clip.width(),
        viewport.width(),
    )
    physical_boundary = (
        snapshot.primary_clip.right() - viewport.left()
    ) * snapshot.device_pixel_ratio
    assert physical_boundary == round(physical_boundary)
