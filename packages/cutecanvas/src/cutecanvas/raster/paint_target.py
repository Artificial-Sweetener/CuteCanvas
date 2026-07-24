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
"""Editable-raster implementation of atomic source-neutral paint targets."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from PySide6.QtGui import QColor
from qpane.sdk.scene import LayerDescriptor, RasterBounds, SceneDescriptor

from cutecanvas.coverage import CoverageCombineMode, CoverageSnapshot
from cutecanvas.fill.sources import SparseFloodFillPixelSource
from cutecanvas.types import RasterExtentPolicy

from ..painting import (
    BrushCompositor,
    BrushDabEngine,
    BrushDabRegionPlanner,
    BrushPreset,
    BrushSourceCoordinateSession,
    BrushStrokeCompiler,
    BrushStrokeSegment,
    FloodFillSource,
    PaintTargetContext,
)
from ..painting.rendering import render_color_dabs
from ..resources import ProjectResourceReference
from ..selection import PixelSelectionService
from .assets import EditableRasterAssetStore
from .color_surface import ColorRasterSurface
from .paint_geometry import (
    PAINT_TILE_SIZE,
    blend_constraint,
    expanded_surface_bounds,
    group_dabs_by_tile,
)
from .paint_history import RasterPaintEdit, RasterPaintHistory, RasterPaintPatch
from .presentation_state import EditableRasterPresentationState
from .stroke_session import RasterStrokeSession, selection_constraint


class EditableRasterPaintTargetOwner:
    """Apply shared brush dabs to editable color surfaces transactionally."""

    def __init__(
        self,
        *,
        assets: EditableRasterAssetStore,
        selections: PixelSelectionService,
        history: RasterPaintHistory,
        changed: Callable[[RasterBounds], None],
        structure_changed: Callable[[], None],
        presentation_state: EditableRasterPresentationState,
        compositor: BrushCompositor | None = None,
    ) -> None:
        """Bind authoritative pixels, selection, history, and publication."""
        self._assets = assets
        self._selections = selections
        self._history = history
        self._changed = changed
        self._structure_changed = structure_changed
        self._presentation_state = presentation_state
        self._dabs = BrushDabEngine()
        self._compiler = BrushStrokeCompiler()
        self._regions = BrushDabRegionPlanner()
        self._compositor = BrushCompositor() if compositor is None else compositor
        self._session: RasterStrokeSession | None = None

    def supports(self, target: PaintTargetContext) -> bool:
        """Return whether ``target`` references editable premultiplied pixels."""
        return target.layer is not None and self._asset(target.layer) is not None

    def begin(self, target: PaintTargetContext) -> bool:
        """Capture structure and projected selection for one paint transaction."""
        scene = target.scene
        layer = target.layer
        if layer is None:
            return False
        asset = self._asset(layer)
        source = layer.source
        if asset is None or not isinstance(source, ProjectResourceReference):
            return False
        if self._session is not None:
            self._cancel_active_session()
        constraint, constrained = selection_constraint(
            self._selections,
            scene,
            layer,
        )
        self._session = RasterStrokeSession(
            scene.scene_id,
            layer.layer_id,
            source.resource_id,
            asset.surface.bounds,
            constraint,
            constrained,
            BrushSourceCoordinateSession(
                (
                    float(asset.surface.bounds.x),
                    float(asset.surface.bounds.y),
                )
            ),
        )
        self._presentation_state.begin(source.resource_id)
        return True

    def apply(
        self,
        target: PaintTargetContext,
        segment: BrushStrokeSegment,
        preset: BrushPreset,
        color: QColor,
    ) -> bool:
        """Apply one segment incrementally across bounded dirty tiles."""
        scene = target.scene
        layer = target.layer
        if layer is None:
            return False
        session = self._matching_session(scene, layer)
        asset = self._asset(layer)
        if session is None or asset is None:
            return False
        surface = asset.surface
        local_segment = self._compiler.compile(
            session.coordinates.layer_segment(
                segment,
                (float(surface.bounds.x), float(surface.bounds.y)),
            ),
            preset,
        )
        dabs = self._dabs.segment_dabs(local_segment)
        requested = self._regions.bounds(dabs)
        if requested is None:
            return False
        if surface.extent_policy is not RasterExtentPolicy.FIXED:
            expanded = expanded_surface_bounds(surface.bounds, requested)
            if surface.ensure_bounds(expanded):
                self._structure_changed()
        writable = surface.bounds.intersection(requested)
        if writable is None:
            return False
        grouped = group_dabs_by_tile(dabs, writable)
        changed_tiles: list[RasterBounds] = []
        for canonical_tile, tile_dabs in grouped.items():
            tile = canonical_tile.intersection(writable)
            if tile is None:
                continue
            before = surface.capture_patch(tile)
            if before is None:
                continue
            session.before_tiles.setdefault(
                canonical_tile,
                surface.capture_region(canonical_tile),
            )
            after = render_color_dabs(
                before=before,
                patch_bounds=tile.to_qrect(),
                dabs=tile_dabs,
                operation=local_segment.operation,
                color=color,
                compositor=self._compositor,
            )
            constraint = session.constraint_pixels(tile)
            if constraint is not None:
                after = blend_constraint(before, after, constraint)
            if np.array_equal(before, after):
                continue
            if surface.restore_patch(tile, after):
                changed_tiles.append(tile)
        for tile in changed_tiles:
            self._changed(tile)
        return bool(changed_tiles)

    def commit(self, target: PaintTargetContext) -> bool:
        """Record one paint command from lazily captured tile deltas."""
        scene = target.scene
        layer = target.layer
        if layer is None:
            self._cancel_active_session()
            return False
        session = self._matching_session(scene, layer)
        asset = self._asset(layer)
        self._session = None
        if session is not None:
            self._presentation_state.end(session.raster_id)
            if asset is not None:
                self._changed(asset.surface.bounds)
        if session is None or asset is None:
            return False
        patches = tuple(
            RasterPaintPatch(tile, before, after)
            for tile, before in session.before_tiles.items()
            if not np.array_equal(
                before,
                (after := asset.surface.capture_region(tile)),
            )
        )
        if not patches:
            if asset.surface.bounds != session.before_bounds:
                asset.surface.set_bounds(session.before_bounds)
                self._structure_changed()
            return False
        self._history.record_applied(
            RasterPaintEdit(
                session.scene_id,
                session.layer_id,
                session.raster_id,
                session.before_bounds,
                asset.surface.bounds,
                patches,
            )
        )
        return True

    def cancel(self, target: PaintTargetContext) -> bool:
        """Restore every captured tile and the exact pre-stroke bounds."""
        scene = target.scene
        layer = target.layer
        if layer is None:
            return self._cancel_active_session()
        session = self._matching_session(scene, layer)
        asset = self._asset(layer)
        self._session = None
        if session is not None:
            self._presentation_state.end(session.raster_id)
        if session is None or asset is None:
            return False
        return self._restore_session(asset.surface, session)

    def preview_color(self, target: PaintTargetContext, fallback: QColor) -> QColor:
        """Return the configured color used by this paint target."""
        return QColor(fallback)

    def flood_fill_source(self, target: PaintTargetContext) -> FloodFillSource | None:
        """Return immutable sparse pixels without materializing their envelope."""
        layer = target.layer
        asset = None if layer is None else self._asset(layer)
        if asset is None:
            return None
        generation, structure, snapshot = asset.surface.versioned_sparse_snapshot()
        source = SparseFloodFillPixelSource(snapshot)
        return FloodFillSource(source, source.bounds, (generation, structure))

    def commit_flood_fill(
        self,
        target: PaintTargetContext,
        coverage: CoverageSnapshot,
        mode: CoverageCombineMode,
        expected_revision: object,
        color: QColor,
    ) -> bool:
        """Commit bucket output only while sampled raster authority is current."""
        layer = target.layer
        asset = None if layer is None else self._asset(layer)
        return bool(
            asset is not None
            and asset.surface.revisions() == expected_revision
            and self.commit_fill_coverage(target, coverage, mode, color)
        )

    def commit_fill_coverage(
        self,
        target: PaintTargetContext,
        coverage: CoverageSnapshot,
        mode: CoverageCombineMode,
        color: QColor,
    ) -> bool:
        """Apply one bounded solid-color or erase fill as a tile-patch edit."""
        if coverage.bounds is None or mode is CoverageCombineMode.INTERSECT:
            return False
        layer = target.layer
        asset = None if layer is None else self._asset(layer)
        source = None if layer is None else layer.source
        if asset is None or not isinstance(source, ProjectResourceReference):
            return False
        if self._session is not None:
            self._cancel_active_session()
        surface = asset.surface
        before_bounds = surface.bounds
        if (
            surface.extent_policy is not RasterExtentPolicy.FIXED
            and surface.ensure_bounds(
                expanded_surface_bounds(surface.bounds, coverage.bounds)
            )
        ):
            self._structure_changed()
        writable = surface.bounds.intersection(coverage.bounds)
        if writable is None:
            return False
        patches: list[RasterPaintPatch] = []
        for tile in _tiles_covering(writable, PAINT_TILE_SIZE):
            before = surface.capture_region(tile)
            mask = _coverage_region(coverage, tile)
            after = _render_coverage_fill(before, mask, color, mode)
            if np.array_equal(before, after) or not surface.restore_patch(tile, after):
                continue
            patches.append(RasterPaintPatch(tile, before, after))
            self._changed(tile)
        if not patches:
            if surface.bounds != before_bounds:
                surface.set_bounds(before_bounds)
                self._structure_changed()
            return False
        self._history.record_applied(
            RasterPaintEdit(
                target.scene.scene_id,
                layer.layer_id,
                source.resource_id,
                before_bounds,
                surface.bounds,
                tuple(patches),
            )
        )
        return True

    def _restore_session(
        self,
        surface: ColorRasterSurface,
        session: RasterStrokeSession,
    ) -> bool:
        """Restore an unresolved transaction without entering history."""
        structure_changed = surface.set_bounds(session.before_bounds)
        changed = structure_changed
        for tile, before in session.before_tiles.items():
            overlap = session.before_bounds.intersection(tile)
            if overlap is None:
                continue
            source_x = overlap.x - tile.x
            source_y = overlap.y - tile.y
            if surface.restore_patch(
                overlap,
                before[
                    source_y : source_y + overlap.height,
                    source_x : source_x + overlap.width,
                ],
            ):
                self._changed(overlap)
                changed = True
        if structure_changed:
            self._structure_changed()
        return changed

    def _cancel_active_session(self) -> bool:
        """Restore and close an unexpected prior transaction before replacement."""
        session = self._session
        self._session = None
        if session is None:
            return False
        self._presentation_state.end(session.raster_id)
        asset = self._assets.get(session.raster_id)
        return bool(asset is not None and self._restore_session(asset.surface, session))

    def _matching_session(
        self, scene: SceneDescriptor, layer: LayerDescriptor
    ) -> RasterStrokeSession | None:
        """Return the active session only for its exact instance."""
        session = self._session
        if session is None:
            return None
        if session.scene_id != scene.scene_id or session.layer_id != layer.layer_id:
            return None
        return session

    def _asset(self, layer: LayerDescriptor):
        """Resolve authoritative color storage for one layer descriptor."""
        source = layer.source
        return (
            None
            if not isinstance(source, ProjectResourceReference)
            else self._assets.get(source.resource_id)
        )


def _tiles_covering(
    bounds: RasterBounds,
    tile_size: int,
) -> tuple[RasterBounds, ...]:
    """Partition writable fill bounds into bounded patch rectangles."""
    return tuple(
        RasterBounds(
            x,
            y,
            min(tile_size, bounds.right - x),
            min(tile_size, bounds.bottom - y),
        )
        for y in range(bounds.y, bounds.bottom, tile_size)
        for x in range(bounds.x, bounds.right, tile_size)
    )


def _coverage_region(
    coverage: CoverageSnapshot,
    bounds: RasterBounds,
) -> np.ndarray:
    """Return zero-padded coverage pixels for one fill tile."""
    result = np.zeros((bounds.height, bounds.width), dtype=np.uint8)
    source_bounds = coverage.bounds
    if source_bounds is None:
        return result
    overlap = source_bounds.intersection(bounds)
    if overlap is None:
        return result
    source_x = overlap.x - source_bounds.x
    source_y = overlap.y - source_bounds.y
    target_x = overlap.x - bounds.x
    target_y = overlap.y - bounds.y
    result[
        target_y : target_y + overlap.height,
        target_x : target_x + overlap.width,
    ] = coverage.pixels[
        source_y : source_y + overlap.height,
        source_x : source_x + overlap.width,
    ]
    return result


def _render_coverage_fill(
    before: np.ndarray,
    coverage: np.ndarray,
    color: QColor,
    mode: CoverageCombineMode,
) -> np.ndarray:
    """Composite premultiplied BGRA paint or erasure through soft coverage."""
    mask = coverage.astype(np.uint16)
    if mode is CoverageCombineMode.SUBTRACT:
        return (
            (before.astype(np.uint16) * (255 - mask[:, :, None]) + 127) // 255
        ).astype(np.uint8)
    alpha = (mask * color.alpha() + 127) // 255
    source = np.empty_like(before, dtype=np.uint16)
    source[:, :, 0] = (alpha * color.blue() + 127) // 255
    source[:, :, 1] = (alpha * color.green() + 127) // 255
    source[:, :, 2] = (alpha * color.red() + 127) // 255
    source[:, :, 3] = alpha
    inverse = 255 - alpha
    return (
        source + (before.astype(np.uint16) * inverse[:, :, None] + 127) // 255
    ).astype(np.uint8)
