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
"""DPR-stable responsive layout for independent render targets."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QPointF, QRectF, QSizeF


@dataclass(frozen=True, slots=True)
class ViewTargetSpec:
    """Describe one independently rendered target for responsive layout."""

    target_id: object
    native_size: QSizeF

    def __post_init__(self) -> None:
        """Detach and validate positive native geometry."""
        size = QSizeF(self.native_size)
        if size.width() <= 0.0 or size.height() <= 0.0:
            raise ValueError("native_size dimensions must be positive")
        object.__setattr__(self, "native_size", size)


class ResponsiveGridTopology(str, Enum):
    """Select the source-neutral rule used to choose grid columns."""

    MINIMUM_CELL_WIDTH = "minimum_cell_width"
    MAXIMUM_REFERENCE_AREA = "maximum_reference_area"


class IncompleteRowAlignment(str, Enum):
    """Select horizontal placement for a non-full final grid row."""

    LEADING = "leading"
    CENTER = "center"


class ResponsiveGridPacking(str, Enum):
    """Select whether target frames fill cells or preserve packed native tiles."""

    UNIFORM_CELLS = "uniform_cells"
    NATIVE_TILES = "native_tiles"


@dataclass(frozen=True, slots=True)
class ResponsiveGridPolicy:
    """Configure logical grid density and spacing."""

    minimum_cell_width: float = 280.0
    gap: float = 8.0
    maximum_columns: int | None = None
    topology: ResponsiveGridTopology = ResponsiveGridTopology.MAXIMUM_REFERENCE_AREA
    topology_hysteresis_ratio: float = 1.02
    incomplete_row_alignment: IncompleteRowAlignment = IncompleteRowAlignment.CENTER
    packing: ResponsiveGridPacking = ResponsiveGridPacking.UNIFORM_CELLS
    native_tile_gap_ratio: float = 0.0
    native_tile_minimum_gap: float = 0.0
    native_tile_viewport_gap: float | None = None

    def __post_init__(self) -> None:
        """Validate physical layout constraints."""
        if self.minimum_cell_width <= 0.0:
            raise ValueError("minimum_cell_width must be positive")
        if self.gap < 0.0:
            raise ValueError("gap must be non-negative")
        if self.maximum_columns is not None and self.maximum_columns <= 0:
            raise ValueError("maximum_columns must be positive or None")
        if not isinstance(self.topology, ResponsiveGridTopology):
            raise TypeError("topology must be a ResponsiveGridTopology")
        if (
            not math.isfinite(self.topology_hysteresis_ratio)
            or self.topology_hysteresis_ratio < 1.0
        ):
            raise ValueError(
                "topology_hysteresis_ratio must be finite and at least one"
            )
        if not isinstance(self.incomplete_row_alignment, IncompleteRowAlignment):
            raise TypeError(
                "incomplete_row_alignment must be an IncompleteRowAlignment"
            )
        if not isinstance(self.packing, ResponsiveGridPacking):
            raise TypeError("packing must be a ResponsiveGridPacking")
        if (
            not math.isfinite(self.native_tile_gap_ratio)
            or self.native_tile_gap_ratio < 0.0
        ):
            raise ValueError("native_tile_gap_ratio must be finite and non-negative")
        if (
            not math.isfinite(self.native_tile_minimum_gap)
            or self.native_tile_minimum_gap < 0.0
        ):
            raise ValueError("native_tile_minimum_gap must be finite and non-negative")
        if self.native_tile_viewport_gap is not None and (
            not math.isfinite(self.native_tile_viewport_gap)
            or self.native_tile_viewport_gap < 0.0
        ):
            raise ValueError(
                "native_tile_viewport_gap must be finite and non-negative or None"
            )


@dataclass(frozen=True, slots=True)
class ViewTargetFrame:
    """Locate one target's cell and aspect-preserving content rectangle."""

    target_id: object
    cell: QRectF
    content: QRectF
    row: int
    column: int


@dataclass(frozen=True, slots=True)
class ResponsiveGridSnapshot:
    """Return one immutable target arrangement with hit-testing helpers."""

    viewport: QRectF
    frames: tuple[ViewTargetFrame, ...]
    rows: int
    columns: int
    device_pixel_ratio: float
    topology: ResponsiveGridTopology = ResponsiveGridTopology.MAXIMUM_REFERENCE_AREA
    retained_previous_topology: bool = False

    def frame(self, target_id: object) -> ViewTargetFrame | None:
        """Return the frame for one target identity."""
        return next(
            (frame for frame in self.frames if frame.target_id == target_id),
            None,
        )

    def hit_test(self, point: QPointF) -> object | None:
        """Return the topmost target whose cell contains ``point``."""
        return next(
            (
                frame.target_id
                for frame in reversed(self.frames)
                if frame.cell.contains(point)
            ),
            None,
        )

    def visible_target_ids(self, clip: QRectF | None = None) -> tuple[object, ...]:
        """Return target IDs whose cells intersect the visible clip."""
        visible = self.viewport if clip is None else self.viewport.intersected(clip)
        return tuple(
            frame.target_id for frame in self.frames if frame.cell.intersects(visible)
        )

    def prefetch_order(self, clip: QRectF | None = None) -> tuple[object, ...]:
        """Order visible targets by physical distance from the visible center."""
        visible_ids = set(self.visible_target_ids(clip))
        visible = self.viewport if clip is None else self.viewport.intersected(clip)
        center = visible.center()
        return tuple(
            frame.target_id
            for frame in sorted(
                (frame for frame in self.frames if frame.target_id in visible_ids),
                key=lambda frame: (
                    _distance_squared(frame.content.center(), center),
                    frame.row,
                    frame.column,
                ),
            )
        )

    def damage_from(
        self,
        previous: ResponsiveGridSnapshot | None,
    ) -> tuple[QRectF, ...]:
        """Return old/new rectangles whose placement changed."""
        if previous is None:
            return tuple(QRectF(frame.cell) for frame in self.frames)
        previous_by_id = {frame.target_id: frame.cell for frame in previous.frames}
        current_by_id = {frame.target_id: frame.cell for frame in self.frames}
        damage: list[QRectF] = []
        target_ids = tuple(frame.target_id for frame in previous.frames) + tuple(
            frame.target_id
            for frame in self.frames
            if frame.target_id not in previous_by_id
        )
        for target_id in target_ids:
            before = previous_by_id.get(target_id)
            after = current_by_id.get(target_id)
            if before == after:
                continue
            if before is not None:
                damage.append(QRectF(before))
            if after is not None:
                damage.append(QRectF(after))
        return tuple(damage)


@dataclass(frozen=True, slots=True)
class _AreaCandidate:
    """Describe one maximum-reference-area topology candidate."""

    columns: int
    rows: int
    displayed_area: float
    empty_cells: int
    orientation_penalty: int


class ResponsiveGridLayout:
    """Arrange independent targets on one stable physical-pixel grid."""

    def __init__(self, policy: ResponsiveGridPolicy | None = None) -> None:
        """Store immutable responsive layout policy."""
        self._policy = policy or ResponsiveGridPolicy()

    @property
    def policy(self) -> ResponsiveGridPolicy:
        """Return the current immutable grid policy."""
        return self._policy

    def arrange(
        self,
        viewport: QRectF,
        targets: tuple[ViewTargetSpec, ...],
        *,
        device_pixel_ratio: float = 1.0,
        previous: ResponsiveGridSnapshot | None = None,
    ) -> ResponsiveGridSnapshot:
        """Arrange targets using physical pixels and return logical geometry.

        Args:
            viewport: Logical viewport bounds available for target cells.
            targets: Stable target identities and their native dimensions.
            device_pixel_ratio: Physical pixels represented by one logical pixel.
            previous: Prior snapshot used only by a hysteretic topology policy.
        """
        if not isinstance(viewport, QRectF):
            raise TypeError("viewport must be a QRectF")
        if viewport.width() < 0.0 or viewport.height() < 0.0:
            raise ValueError("viewport dimensions must be non-negative")
        dpr = float(device_pixel_ratio)
        if not math.isfinite(dpr) or dpr <= 0.0:
            raise ValueError("device_pixel_ratio must be positive and finite")
        if len({target.target_id for target in targets}) != len(targets):
            raise ValueError("target IDs must be unique")
        if not targets:
            return ResponsiveGridSnapshot(
                QRectF(viewport),
                (),
                0,
                0,
                dpr,
                self._policy.topology,
            )

        physical_width = max(0, round(viewport.width() * dpr))
        physical_height = max(0, round(viewport.height() * dpr))
        if self._policy.packing is ResponsiveGridPacking.NATIVE_TILES:
            return self._arrange_native_tiles(
                viewport,
                targets,
                physical_width=physical_width,
                physical_height=physical_height,
                device_pixel_ratio=dpr,
                previous=previous,
            )
        requested_gap = round(self._policy.gap * dpr)
        minimum_width = max(1, round(self._policy.minimum_cell_width * dpr))
        columns, retained_previous_topology = self._columns_for(
            targets,
            physical_width=physical_width,
            physical_height=physical_height,
            minimum_width=minimum_width,
            gap=requested_gap,
            previous=previous,
            device_pixel_ratio=dpr,
        )
        rows = math.ceil(len(targets) / columns)
        horizontal_gap = _bounded_gap(requested_gap, physical_width, columns)
        vertical_gap = _bounded_gap(requested_gap, physical_height, rows)
        cell_widths = _partition(
            physical_width - horizontal_gap * (columns - 1),
            columns,
        )
        cell_heights = _partition(
            physical_height - vertical_gap * (rows - 1),
            rows,
        )
        x_offsets = _offsets(cell_widths, horizontal_gap)
        y_offsets = _offsets(cell_heights, vertical_gap)
        frames = self._frames(
            targets,
            columns=columns,
            rows=rows,
            viewport=viewport,
            dpr=dpr,
            physical_width=physical_width,
            gap=horizontal_gap,
            x_offsets=x_offsets,
            y_offsets=y_offsets,
            cell_widths=cell_widths,
            cell_heights=cell_heights,
        )
        return ResponsiveGridSnapshot(
            QRectF(viewport),
            frames,
            rows,
            columns,
            dpr,
            self._policy.topology,
            retained_previous_topology,
        )

    def _arrange_native_tiles(
        self,
        viewport: QRectF,
        targets: tuple[ViewTargetSpec, ...],
        *,
        physical_width: int,
        physical_height: int,
        device_pixel_ratio: float,
        previous: ResponsiveGridSnapshot | None,
    ) -> ResponsiveGridSnapshot:
        """Pack uniform native-aspect tile frames into the available viewport."""
        columns, retained_previous_topology = self._native_tile_columns_for(
            targets,
            physical_width=physical_width,
            physical_height=physical_height,
            previous=previous,
            device_pixel_ratio=device_pixel_ratio,
        )
        rows = math.ceil(len(targets) / columns)
        reference = _physical_size(targets[0].native_size, device_pixel_ratio)
        scale, displayed_gap = _native_tile_metrics(
            reference=reference,
            columns=columns,
            rows=rows,
            physical_width=physical_width,
            physical_height=physical_height,
            ratio=self._policy.native_tile_gap_ratio,
            minimum=self._policy.native_tile_minimum_gap * device_pixel_ratio,
            viewport_gap=(
                None
                if self._policy.native_tile_viewport_gap is None
                else self._policy.native_tile_viewport_gap * device_pixel_ratio
            ),
        )
        packed_width = (
            columns * reference.width() * scale + (columns - 1) * displayed_gap
        )
        packed_height = rows * reference.height() * scale + (rows - 1) * displayed_gap
        origin_x = (physical_width - packed_width) * 0.5
        origin_y = (physical_height - packed_height) * 0.5
        frames = _native_tile_frames(
            targets,
            columns=columns,
            rows=rows,
            viewport=viewport,
            device_pixel_ratio=device_pixel_ratio,
            reference=reference,
            displayed_gap=displayed_gap,
            scale=scale,
            origin_x=origin_x,
            origin_y=origin_y,
            incomplete_row_alignment=self._policy.incomplete_row_alignment,
        )
        return ResponsiveGridSnapshot(
            QRectF(viewport),
            frames,
            rows,
            columns,
            device_pixel_ratio,
            self._policy.topology,
            retained_previous_topology,
        )

    def _native_tile_columns_for(
        self,
        targets: tuple[ViewTargetSpec, ...],
        *,
        physical_width: int,
        physical_height: int,
        previous: ResponsiveGridSnapshot | None,
        device_pixel_ratio: float,
    ) -> tuple[int, bool]:
        """Choose a packed-native topology using the normal hysteresis rule."""
        maximum = min(
            len(targets),
            self._policy.maximum_columns or len(targets),
        )
        reference = _physical_size(targets[0].native_size, device_pixel_ratio)
        candidates = tuple(
            _native_tile_candidate(
                columns,
                target_count=len(targets),
                reference=reference,
                physical_width=physical_width,
                physical_height=physical_height,
                ratio=self._policy.native_tile_gap_ratio,
                minimum=self._policy.native_tile_minimum_gap * device_pixel_ratio,
                viewport_gap=(
                    None
                    if self._policy.native_tile_viewport_gap is None
                    else self._policy.native_tile_viewport_gap * device_pixel_ratio
                ),
            )
            for columns in range(1, maximum + 1)
        )
        best = candidates[0]
        for candidate in candidates[1:]:
            if _area_candidate_is_better(candidate, best):
                best = candidate
        previous_columns = None if previous is None else previous.columns
        previous_candidate = next(
            (
                candidate
                for candidate in candidates
                if candidate.columns == previous_columns
            ),
            None,
        )
        if (
            previous_candidate is not None
            and previous_candidate.displayed_area > 0.0
            and best.displayed_area
            < previous_candidate.displayed_area * self._policy.topology_hysteresis_ratio
        ):
            return previous_candidate.columns, True
        return best.columns, False

    def _columns_for(
        self,
        targets: tuple[ViewTargetSpec, ...],
        *,
        physical_width: int,
        physical_height: int,
        minimum_width: int,
        gap: int,
        previous: ResponsiveGridSnapshot | None,
        device_pixel_ratio: float,
    ) -> tuple[int, bool]:
        """Choose columns through the configured source-neutral topology policy."""
        maximum = min(
            len(targets),
            self._policy.maximum_columns or len(targets),
        )
        if self._policy.topology is ResponsiveGridTopology.MINIMUM_CELL_WIDTH:
            available_columns = max(
                1,
                (physical_width + gap) // max(1, minimum_width + gap),
            )
            return min(maximum, available_columns), False
        candidates = tuple(
            _area_candidate(
                columns,
                target_count=len(targets),
                reference_size=targets[0].native_size,
                physical_width=physical_width,
                physical_height=physical_height,
                gap=gap,
                device_pixel_ratio=device_pixel_ratio,
            )
            for columns in range(1, maximum + 1)
        )
        best = candidates[0]
        for candidate in candidates[1:]:
            if _area_candidate_is_better(candidate, best):
                best = candidate
        previous_columns = None if previous is None else previous.columns
        previous_candidate = next(
            (
                candidate
                for candidate in candidates
                if candidate.columns == previous_columns
            ),
            None,
        )
        if (
            previous_candidate is not None
            and previous_candidate.displayed_area > 0.0
            and best.displayed_area
            < previous_candidate.displayed_area * self._policy.topology_hysteresis_ratio
        ):
            return previous_candidate.columns, True
        return best.columns, False

    def _frames(
        self,
        targets: tuple[ViewTargetSpec, ...],
        *,
        columns: int,
        rows: int,
        viewport: QRectF,
        dpr: float,
        physical_width: int,
        gap: int,
        x_offsets: tuple[int, ...],
        y_offsets: tuple[int, ...],
        cell_widths: tuple[int, ...],
        cell_heights: tuple[int, ...],
    ) -> tuple[ViewTargetFrame, ...]:
        """Build stable target frames with the configured final-row alignment."""
        final_row_count = len(targets) - (rows - 1) * columns
        final_row_offset = 0
        if (
            self._policy.incomplete_row_alignment is IncompleteRowAlignment.CENTER
            and final_row_count < columns
        ):
            occupied_width = sum(cell_widths[:final_row_count]) + gap * max(
                0, final_row_count - 1
            )
            final_row_offset = max(0, (physical_width - occupied_width) // 2)
        frames: list[ViewTargetFrame] = []
        for index, target in enumerate(targets):
            row, column = divmod(index, columns)
            x_offset = (
                final_row_offset + sum(cell_widths[:column]) + gap * column
                if row == rows - 1 and final_row_count < columns
                else x_offsets[column]
            )
            frames.append(
                _frame(
                    target,
                    index,
                    columns,
                    viewport,
                    dpr,
                    x_offset,
                    y_offsets[row],
                    cell_widths[column],
                    cell_heights[row],
                )
            )
        return tuple(frames)


def _frame(
    target: ViewTargetSpec,
    index: int,
    columns: int,
    viewport: QRectF,
    dpr: float,
    x_offset: int,
    y_offset: int,
    width: int,
    height: int,
) -> ViewTargetFrame:
    """Build one logical frame from an exact physical cell."""
    row, column = divmod(index, columns)
    cell = QRectF(
        viewport.x() + x_offset / dpr,
        viewport.y() + y_offset / dpr,
        width / dpr,
        height / dpr,
    )
    content = _contain(cell, target.native_size)
    return ViewTargetFrame(target.target_id, cell, content, row, column)


def _area_candidate(
    columns: int,
    *,
    target_count: int,
    reference_size: QSizeF,
    physical_width: int,
    physical_height: int,
    gap: int,
    device_pixel_ratio: float,
) -> _AreaCandidate:
    """Score one topology by its reference target's displayed physical area."""
    rows = math.ceil(target_count / columns)
    horizontal_gap = _bounded_gap(gap, physical_width, columns)
    vertical_gap = _bounded_gap(gap, physical_height, rows)
    cell_width = max(
        0,
        (physical_width - horizontal_gap * (columns - 1)) / columns,
    )
    cell_height = max(
        0,
        (physical_height - vertical_gap * (rows - 1)) / rows,
    )
    reference_width = reference_size.width() * device_pixel_ratio
    reference_height = reference_size.height() * device_pixel_ratio
    scale = min(
        cell_width / reference_width,
        cell_height / reference_height,
    )
    return _AreaCandidate(
        columns,
        rows,
        reference_width * reference_height * scale * scale,
        columns * rows - target_count,
        _orientation_penalty(columns, rows, reference_size),
    )


def _native_tile_candidate(
    columns: int,
    *,
    target_count: int,
    reference: QSizeF,
    physical_width: int,
    physical_height: int,
    ratio: float,
    minimum: float,
    viewport_gap: float | None,
) -> _AreaCandidate:
    """Score one native-tile topology against the physical viewport."""
    rows = math.ceil(target_count / columns)
    scale, _displayed_gap = _native_tile_metrics(
        reference=reference,
        columns=columns,
        rows=rows,
        physical_width=physical_width,
        physical_height=physical_height,
        ratio=ratio,
        minimum=minimum,
        viewport_gap=viewport_gap,
    )
    return _AreaCandidate(
        columns,
        rows,
        reference.width() * reference.height() * scale * scale,
        columns * rows - target_count,
        _orientation_penalty(columns, rows, reference),
    )


def _physical_size(native_size: QSizeF, device_pixel_ratio: float) -> QSizeF:
    """Return one target's native size in physical-pixel layout units."""
    return QSizeF(
        native_size.width() * device_pixel_ratio,
        native_size.height() * device_pixel_ratio,
    )


def _native_tile_gap(
    reference: QSizeF,
    *,
    columns: int,
    rows: int,
    ratio: float,
    minimum: float,
) -> float:
    """Resolve proportional native-scene spacing for one packed topology."""
    horizontal_span = columns * reference.width()
    vertical_span = rows * reference.height()
    if horizontal_span >= vertical_span:
        packed_span = horizontal_span
        gap_count = max(0, columns - 1)
    else:
        packed_span = vertical_span
        gap_count = max(0, rows - 1)
    denominator = 1.0 - ratio * gap_count
    proportional = 0.0 if denominator <= 0.0 else ratio * packed_span / denominator
    return max(minimum, proportional)


def _native_tile_metrics(
    *,
    reference: QSizeF,
    columns: int,
    rows: int,
    physical_width: int,
    physical_height: int,
    ratio: float,
    minimum: float,
    viewport_gap: float | None,
) -> tuple[float, float]:
    """Resolve one native-tile scale and its displayed physical gutter."""

    if viewport_gap is None:
        scene_gap = _native_tile_gap(
            reference,
            columns=columns,
            rows=rows,
            ratio=ratio,
            minimum=minimum,
        )
        scene_width = columns * reference.width() + (columns - 1) * scene_gap
        scene_height = rows * reference.height() + (rows - 1) * scene_gap
        scale = min(
            physical_width / scene_width if scene_width > 0.0 else 0.0,
            physical_height / scene_height if scene_height > 0.0 else 0.0,
        )
        return scale, scene_gap * scale

    displayed_gap = min(
        viewport_gap,
        physical_width / max(1, columns - 1),
        physical_height / max(1, rows - 1),
    )
    available_width = max(0.0, physical_width - (columns - 1) * displayed_gap)
    available_height = max(0.0, physical_height - (rows - 1) * displayed_gap)
    horizontal_scale = available_width / (columns * reference.width())
    vertical_scale = available_height / (rows * reference.height())
    if horizontal_scale <= vertical_scale:
        stable_tile_width = math.floor(available_width / columns)
        return stable_tile_width / reference.width(), displayed_gap
    stable_tile_height = math.floor(available_height / rows)
    return stable_tile_height / reference.height(), displayed_gap


def _native_tile_frames(
    targets: tuple[ViewTargetSpec, ...],
    *,
    columns: int,
    rows: int,
    viewport: QRectF,
    device_pixel_ratio: float,
    reference: QSizeF,
    displayed_gap: float,
    scale: float,
    origin_x: float,
    origin_y: float,
    incomplete_row_alignment: IncompleteRowAlignment,
) -> tuple[ViewTargetFrame, ...]:
    """Build native-aspect frames with the prior centered-final-row geometry."""
    frames: list[ViewTargetFrame] = []
    final_row_count = len(targets) - (rows - 1) * columns
    tile_width = reference.width() * scale
    tile_height = reference.height() * scale
    packed_width = columns * tile_width + (columns - 1) * displayed_gap
    for index, target in enumerate(targets):
        row, column = divmod(index, columns)
        row_count = final_row_count if row == rows - 1 else columns
        row_width = row_count * tile_width + max(0, row_count - 1) * displayed_gap
        row_offset = (
            (packed_width - row_width) * 0.5
            if (
                incomplete_row_alignment is IncompleteRowAlignment.CENTER
                and row == rows - 1
                and final_row_count < columns
            )
            else 0.0
        )
        x = origin_x + row_offset + column * (tile_width + displayed_gap)
        y = origin_y + row * (tile_height + displayed_gap)
        cell = QRectF(
            viewport.x() + x / device_pixel_ratio,
            viewport.y() + y / device_pixel_ratio,
            tile_width / device_pixel_ratio,
            tile_height / device_pixel_ratio,
        )
        frames.append(
            ViewTargetFrame(
                target.target_id, cell, _contain(cell, target.native_size), row, column
            )
        )
    return tuple(frames)


def _area_candidate_is_better(
    candidate: _AreaCandidate,
    current: _AreaCandidate,
) -> bool:
    """Resolve area ties deterministically without target-domain knowledge."""
    area_delta = candidate.displayed_area - current.displayed_area
    if area_delta > 1e-9:
        return True
    if area_delta < -1e-9:
        return False
    if candidate.empty_cells != current.empty_cells:
        return candidate.empty_cells < current.empty_cells
    if candidate.orientation_penalty != current.orientation_penalty:
        return candidate.orientation_penalty < current.orientation_penalty
    return candidate.columns < current.columns


def _orientation_penalty(
    columns: int,
    rows: int,
    reference_size: QSizeF,
) -> int:
    """Prefer grid orientation that agrees with the reference target shape."""
    if reference_size.width() < reference_size.height():
        return max(0, columns - rows)
    if reference_size.width() > reference_size.height():
        return max(0, rows - columns)
    return abs(columns - rows)


def _partition(total: int, count: int) -> tuple[int, ...]:
    """Partition integer physical pixels without cumulative rounding drift."""
    total = max(0, total)
    base, remainder = divmod(total, count)
    return tuple(base + (1 if index < remainder else 0) for index in range(count))


def _bounded_gap(requested: int, extent: int, count: int) -> int:
    """Fit gaps inside the physical extent even for degenerate viewports."""
    if count <= 1:
        return 0
    return min(requested, max(0, extent // (count - 1)))


def _offsets(sizes: tuple[int, ...], gap: int) -> tuple[int, ...]:
    """Return physical leading offsets for partitioned rows or columns."""
    values: list[int] = []
    current = 0
    for size in sizes:
        values.append(current)
        current += size + gap
    return tuple(values)


def _contain(cell: QRectF, native: QSizeF) -> QRectF:
    """Aspect-fit native geometry inside one cell."""
    if cell.isEmpty():
        return QRectF(cell.x(), cell.y(), 0.0, 0.0)
    scale = min(
        cell.width() / native.width(),
        cell.height() / native.height(),
    )
    width = native.width() * scale
    height = native.height() * scale
    return QRectF(
        cell.center().x() - width * 0.5,
        cell.center().y() - height * 0.5,
        width,
        height,
    )


def _distance_squared(first: QPointF, second: QPointF) -> float:
    """Return squared Euclidean distance without an unnecessary square root."""
    dx = first.x() - second.x()
    dy = first.y() - second.y()
    return dx * dx + dy * dy
