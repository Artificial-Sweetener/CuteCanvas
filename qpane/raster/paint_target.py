#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Editable-raster implementation of atomic source-neutral paint targets."""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
from PySide6.QtGui import QColor

from ..composition.edit_controller import CompositionEditController
from ..coverage import CoverageSnapshot
from ..painting import (
    BrushCompositor,
    BrushDab,
    BrushDabEngine,
    BrushDabRegionPlanner,
    BrushPreset,
    BrushSourceCoordinateSession,
    BrushStrokeCompiler,
    BrushStrokeSegment,
    PaintTargetContext,
)
from ..painting.rendering import render_color_dabs
from ..scene.model import LayerDescriptor, SceneDescriptor
from ..scene.raster import RasterBounds, RasterExtentPolicy
from ..selection import LayerCoverageProjector, PixelSelectionService
from .assets import EditableRasterAssetStore
from .color_surface import ColorRasterSurface
from .presentation_state import EditableRasterPresentationState
from .source_reference import EditableRasterReference

_PAINT_TILE_SIZE = 128
_EXPANSION_MARGIN = 256


@dataclass(frozen=True, slots=True)
class RasterPaintPatch:
    """Retain one bounded changed tile for exact paint history."""

    bounds: RasterBounds
    before: np.ndarray
    after: np.ndarray

    def __post_init__(self) -> None:
        """Detach and validate premultiplied tile pixels."""
        expected = (self.bounds.height, self.bounds.width, 4)
        before = np.array(self.before, copy=True, order="C")
        after = np.array(self.after, copy=True, order="C")
        if (
            before.dtype != np.uint8
            or after.dtype != np.uint8
            or before.shape != expected
            or after.shape != expected
        ):
            raise ValueError("paint patch pixels must match BGRA tile bounds")
        before.flags.writeable = False
        after.flags.writeable = False
        object.__setattr__(self, "before", before)
        object.__setattr__(self, "after", after)

    @property
    def retained_bytes(self) -> int:
        """Return exact history bytes retained by this tile."""
        return int(self.before.nbytes + self.after.nbytes)


@dataclass(frozen=True, slots=True)
class RasterPaintEdit:
    """Capture one complete paint stroke as bounded tile transitions."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    raster_id: uuid.UUID
    before_bounds: RasterBounds
    after_bounds: RasterBounds
    patches: tuple[RasterPaintPatch, ...]

    @property
    def scope_id(self) -> uuid.UUID:
        """Return the scene history scope owning this stroke."""
        return self.scene_id

    @property
    def retained_bytes(self) -> int:
        """Return exact retained patch bytes plus compact metadata."""
        return 256 + sum(patch.retained_bytes for patch in self.patches)

    @property
    def retained_resources(self) -> tuple[EditableRasterReference, ...]:
        """Retain the edited raster while this command remains in history."""
        return (EditableRasterReference(self.raster_id),)


@dataclass(slots=True)
class _RasterPaintSession:
    """Own one unresolved stroke's original tiles and selection constraint."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    raster_id: uuid.UUID
    before_bounds: RasterBounds
    constraint: CoverageSnapshot | None
    constrained: bool
    coordinates: BrushSourceCoordinateSession
    before_tiles: dict[RasterBounds, np.ndarray] = field(default_factory=dict)


class EditableRasterPaintTargetOwner:
    """Apply shared brush dabs to editable color surfaces transactionally."""

    def __init__(
        self,
        *,
        assets: EditableRasterAssetStore,
        selections: PixelSelectionService,
        edits: CompositionEditController,
        changed: Callable[[RasterBounds], None],
        structure_changed: Callable[[], None],
        presentation_state: EditableRasterPresentationState,
        compositor: BrushCompositor | None = None,
    ) -> None:
        """Bind authoritative pixels, selection, history, and publication."""
        self._assets = assets
        self._selections = selections
        self._edits = edits
        self._changed = changed
        self._structure_changed = structure_changed
        self._presentation_state = presentation_state
        self._projector = LayerCoverageProjector()
        self._dabs = BrushDabEngine()
        self._compiler = BrushStrokeCompiler()
        self._regions = BrushDabRegionPlanner()
        self._compositor = BrushCompositor() if compositor is None else compositor
        self._session: _RasterPaintSession | None = None
        edits.register_handler(
            RasterPaintEdit,
            undo=self._undo,
            redo=self._redo,
        )

    def supports(self, target: PaintTargetContext) -> bool:
        """Return whether ``target`` references editable premultiplied pixels."""
        return target.layer is not None and isinstance(
            target.layer.source, EditableRasterReference
        )

    def begin(self, target: PaintTargetContext) -> bool:
        """Capture structure and projected selection for one paint transaction."""
        scene = target.scene
        layer = target.layer
        if layer is None:
            return False
        asset = self._asset(layer)
        source = layer.source
        if asset is None or not isinstance(source, EditableRasterReference):
            return False
        if self._session is not None:
            self._cancel_active_session()
        scene_selection = self._selections.state(scene.scene_id).coverage
        constraint = None
        if (
            scene_selection is not None
            and layer.transform is not None
            and layer.raster_bounds is not None
        ):
            constraint = self._projector.project_to_layer(
                scene_selection,
                layer.transform,
                layer.raster_bounds,
            )
        self._session = _RasterPaintSession(
            scene.scene_id,
            layer.layer_id,
            source.raster_id,
            asset.surface.bounds,
            constraint,
            scene_selection is not None,
            BrushSourceCoordinateSession(
                (
                    float(asset.surface.bounds.x),
                    float(asset.surface.bounds.y),
                )
            ),
        )
        self._presentation_state.begin(source.raster_id)
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
            expanded = _expanded_surface_bounds(surface.bounds, requested)
            if surface.ensure_bounds(expanded):
                self._structure_changed()
        writable = surface.bounds.intersection(requested)
        if writable is None:
            return False
        grouped = _group_dabs_by_tile(dabs, writable)
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
            constraint = self._constraint_pixels(session, tile)
            if constraint is not None:
                after = _blend_constraint(before, after, constraint)
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
        self._edits.record_applied(
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

    def _undo(self, command: object) -> bool:
        """Restore the exact raster state preceding one paint stroke."""
        return self._restore_edit(command, use_after=False)

    def _redo(self, command: object) -> bool:
        """Restore the exact raster state following one paint stroke."""
        return self._restore_edit(command, use_after=True)

    def _restore_edit(self, command: object, *, use_after: bool) -> bool:
        """Replay one paint command directly through its retained source."""
        if not isinstance(command, RasterPaintEdit):
            return False
        asset = self._assets.get(command.raster_id)
        if asset is None:
            return False
        surface = asset.surface
        target_bounds = command.after_bounds if use_after else command.before_bounds
        structure_changed = surface.set_bounds(target_bounds)
        for patch in command.patches:
            overlap = target_bounds.intersection(patch.bounds)
            if overlap is None:
                continue
            pixels = patch.after if use_after else patch.before
            source_x = overlap.x - patch.bounds.x
            source_y = overlap.y - patch.bounds.y
            surface.restore_patch(
                overlap,
                pixels[
                    source_y : source_y + overlap.height,
                    source_x : source_x + overlap.width,
                ],
            )
            self._changed(overlap)
        if structure_changed:
            self._structure_changed()
        return True

    def _restore_session(
        self,
        surface: ColorRasterSurface,
        session: _RasterPaintSession,
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

    def _constraint_pixels(
        self, session: _RasterPaintSession, bounds: RasterBounds
    ) -> np.ndarray | None:
        """Return local selection coverage for one tile, including empty selection."""
        if not session.constrained:
            return None
        pixels = np.zeros((bounds.height, bounds.width), dtype=np.uint8)
        constraint = session.constraint
        if constraint is None or constraint.bounds is None:
            return pixels
        overlap = constraint.bounds.intersection(bounds)
        if overlap is None:
            return pixels
        source_x = overlap.x - constraint.bounds.x
        source_y = overlap.y - constraint.bounds.y
        target_x = overlap.x - bounds.x
        target_y = overlap.y - bounds.y
        pixels[
            target_y : target_y + overlap.height,
            target_x : target_x + overlap.width,
        ] = constraint.pixels[
            source_y : source_y + overlap.height,
            source_x : source_x + overlap.width,
        ]
        return pixels

    def _matching_session(
        self, scene: SceneDescriptor, layer: LayerDescriptor
    ) -> _RasterPaintSession | None:
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
            if not isinstance(source, EditableRasterReference)
            else self._assets.get(source.raster_id)
        )


def _expanded_surface_bounds(
    current: RasterBounds, requested: RasterBounds
) -> RasterBounds:
    """Grow geometrically so long edge strokes avoid repeated full reframing."""
    if current.contains(requested):
        return current
    horizontal_slack = max(_EXPANSION_MARGIN, current.width // 2)
    vertical_slack = max(_EXPANSION_MARGIN, current.height // 2)
    left = requested.x - horizontal_slack if requested.x < current.x else current.x
    top = requested.y - vertical_slack if requested.y < current.y else current.y
    right = (
        requested.right + horizontal_slack
        if requested.right > current.right
        else current.right
    )
    bottom = (
        requested.bottom + vertical_slack
        if requested.bottom > current.bottom
        else current.bottom
    )
    return RasterBounds(left, top, right - left, bottom - top)


def _group_dabs_by_tile(
    dabs: tuple[BrushDab, ...], writable: RasterBounds
) -> dict[RasterBounds, tuple[BrushDab, ...]]:
    """Spatially bin dabs so long diagonal strokes never allocate their AABB."""
    grouped: dict[RasterBounds, list[BrushDab]] = {}
    for dab in dabs:
        radius = dab.diameter / 2.0 + 1.0
        left = math.floor((dab.center[0] - radius) / _PAINT_TILE_SIZE)
        top = math.floor((dab.center[1] - radius) / _PAINT_TILE_SIZE)
        right = math.floor((dab.center[0] + radius) / _PAINT_TILE_SIZE)
        bottom = math.floor((dab.center[1] + radius) / _PAINT_TILE_SIZE)
        for tile_y in range(top, bottom + 1):
            for tile_x in range(left, right + 1):
                tile = RasterBounds(
                    tile_x * _PAINT_TILE_SIZE,
                    tile_y * _PAINT_TILE_SIZE,
                    _PAINT_TILE_SIZE,
                    _PAINT_TILE_SIZE,
                )
                if tile.intersection(writable) is not None:
                    grouped.setdefault(tile, []).append(dab)
    return {bounds: tuple(values) for bounds, values in grouped.items()}


def _blend_constraint(
    before: np.ndarray,
    painted: np.ndarray,
    constraint: np.ndarray,
) -> np.ndarray:
    """Blend premultiplied paint through one soft selection constraint."""
    coverage = constraint.astype(np.uint16)[:, :, np.newaxis]
    inverse = 255 - coverage
    return (
        (
            before.astype(np.uint16) * inverse
            + painted.astype(np.uint16) * coverage
            + 127
        )
        // 255
    ).astype(np.uint8)
