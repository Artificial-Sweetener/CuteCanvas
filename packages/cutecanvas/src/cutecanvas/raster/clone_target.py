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
"""Editable-raster transaction target for revision-stable Clone Stamp strokes."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from qpane.sdk.rendering import SceneRegionRasterizer
from qpane.sdk.scene import (
    LayerDescriptor,
    RasterBounds,
    SceneDescriptor,
)

from ..painting import (
    BrushCompositor,
    BrushDabEngine,
    BrushDabRegionPlanner,
    BrushPreset,
    BrushSourceCoordinateSession,
    BrushStrokeCompiler,
    BrushStrokeSegment,
    PaintTargetContext,
)
from ..painting.clone_compositor import CloneStampCompositor
from ..painting.clone_model import CloneStampMapping
from ..resources import ProjectResourceReference
from ..selection import PixelSelectionService
from ..types import RasterExtentPolicy
from .assets import EditableRasterAsset, EditableRasterAssetStore
from .clone_sampling import CloneSourceSampler
from .color_surface import ColorRasterSurface
from .paint_geometry import (
    blend_constraint,
    expanded_surface_bounds,
    group_dabs_by_tile,
)
from .paint_history import RasterPaintEdit, RasterPaintHistory, RasterPaintPatch
from .presentation_state import EditableRasterPresentationState
from .revision_reader import RasterRevisionReader
from .stroke_session import RasterStrokeSession, selection_constraint


@dataclass(slots=True)
class _CloneRasterSession:
    """Combine generic raster transaction state with a pre-stroke reader."""

    stroke: RasterStrokeSession
    sampler: CloneSourceSampler


class EditableRasterCloneTarget:
    """Apply cloned color pixels to editable raster layers transactionally."""

    def __init__(
        self,
        *,
        assets: EditableRasterAssetStore,
        selections: PixelSelectionService,
        history: RasterPaintHistory,
        changed: Callable[[RasterBounds], None],
        structure_changed: Callable[[], None],
        presentation_state: EditableRasterPresentationState,
        compositor: BrushCompositor,
        scene_rasterizer: SceneRegionRasterizer,
    ) -> None:
        """Bind raster authority, shared history, presentation, and brush products."""
        self._assets = assets
        self._selections = selections
        self._history = history
        self._changed = changed
        self._structure_changed = structure_changed
        self._presentation_state = presentation_state
        self._compiler = BrushStrokeCompiler()
        self._dabs = BrushDabEngine()
        self._regions = BrushDabRegionPlanner()
        self._compositor = CloneStampCompositor(compositor)
        self._scene_rasterizer = scene_rasterizer
        self._session: _CloneRasterSession | None = None

    def supports_clone(self, target: PaintTargetContext) -> bool:
        """Return whether the target exposes editable premultiplied pixels."""
        return target.layer is not None and self._asset(target.layer) is not None

    def begin_clone(self, target: PaintTargetContext) -> bool:
        """Capture target geometry, selection, and a copy-on-write source reader."""
        layer = target.layer
        asset = None if layer is None else self._asset(layer)
        source = None if layer is None else layer.source
        if (
            layer is None
            or asset is None
            or not isinstance(source, ProjectResourceReference)
        ):
            return False
        if self._session is not None:
            self._cancel_active_session()
        constraint, constrained = selection_constraint(
            self._selections,
            target.scene,
            layer,
        )
        stroke = RasterStrokeSession(
            target.scene.scene_id,
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
        self._session = _CloneRasterSession(
            stroke,
            CloneSourceSampler(
                source=RasterRevisionReader(asset.surface),
                scene=target.scene,
                scene_rasterizer=self._scene_rasterizer,
                resource_revision=self._resource_revision,
                target_resource_id=source.resource_id,
            ),
        )
        self._presentation_state.begin(source.resource_id)
        return True

    def apply_clone(
        self,
        target: PaintTargetContext,
        segment: BrushStrokeSegment,
        preset: BrushPreset,
        mapping: CloneStampMapping,
    ) -> bool:
        """Apply one clone segment across only its intersecting sparse tiles."""
        layer = target.layer
        asset = None if layer is None else self._asset(layer)
        session = None if layer is None else self._matching_session(target.scene, layer)
        if asset is None or session is None:
            return False
        if not session.sampler.source_is_current(mapping):
            self._session = None
            self._presentation_state.end(session.stroke.raster_id)
            self._restore_session(asset.surface, session.stroke)
            return False
        surface = asset.surface
        local_segment = self._compiler.compile(
            session.stroke.coordinates.layer_segment(
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
        changed_tiles: list[RasterBounds] = []
        for canonical_tile, tile_dabs in group_dabs_by_tile(dabs, writable).items():
            tile = canonical_tile.intersection(writable)
            if tile is None:
                continue
            before = surface.capture_patch(tile)
            if before is None:
                continue
            session.sampler.source.preserve(canonical_tile)
            session.stroke.before_tiles.setdefault(
                canonical_tile,
                surface.capture_region(canonical_tile),
            )
            source_pixels = session.sampler.pixels(
                layer,
                tile,
                mapping,
            )
            if source_pixels is None:
                continue
            after = self._compositor.render_dabs(
                before=before,
                source_pixels=source_pixels,
                patch_bounds=tile,
                dabs=tile_dabs,
            )
            constraint = session.stroke.constraint_pixels(tile)
            if constraint is not None:
                after = blend_constraint(before, after, constraint)
            if np.array_equal(before, after):
                continue
            if surface.restore_patch(tile, after):
                changed_tiles.append(tile)
        for tile in changed_tiles:
            self._changed(tile)
        return bool(changed_tiles)

    def commit_clone(self, target: PaintTargetContext) -> bool:
        """Commit one clone stroke from lazily retained tile transitions."""
        layer = target.layer
        asset = None if layer is None else self._asset(layer)
        session = None if layer is None else self._matching_session(target.scene, layer)
        self._session = None
        if session is not None:
            self._presentation_state.end(session.stroke.raster_id)
            if asset is not None:
                self._changed(asset.surface.bounds)
        if session is None or asset is None:
            return False
        stroke = session.stroke
        patches = tuple(
            RasterPaintPatch(tile, before, after)
            for tile, before in stroke.before_tiles.items()
            if not np.array_equal(
                before,
                (after := asset.surface.capture_region(tile)),
            )
        )
        if not patches:
            if asset.surface.bounds != stroke.before_bounds:
                asset.surface.set_bounds(stroke.before_bounds)
                self._structure_changed()
            return False
        self._history.record_applied(
            RasterPaintEdit(
                stroke.scene_id,
                stroke.layer_id,
                stroke.raster_id,
                stroke.before_bounds,
                asset.surface.bounds,
                patches,
            )
        )
        return True

    def cancel_clone(self, target: PaintTargetContext) -> bool:
        """Restore every destination tile and the exact pre-stroke bounds."""
        layer = target.layer
        session = None if layer is None else self._matching_session(target.scene, layer)
        asset = None if layer is None else self._asset(layer)
        self._session = None
        if session is not None:
            self._presentation_state.end(session.stroke.raster_id)
        return bool(
            session is not None
            and asset is not None
            and self._restore_session(asset.surface, session.stroke)
        )

    def _restore_session(
        self,
        surface: ColorRasterSurface,
        stroke: RasterStrokeSession,
    ) -> bool:
        """Restore one unresolved transaction without entering history."""
        structure_changed = surface.set_bounds(stroke.before_bounds)
        changed = structure_changed
        for tile, before in stroke.before_tiles.items():
            overlap = stroke.before_bounds.intersection(tile)
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
        """Cancel an unexpected previous clone transaction before replacement."""
        session = self._session
        self._session = None
        if session is None:
            return False
        stroke = session.stroke
        self._presentation_state.end(stroke.raster_id)
        asset = self._assets.get(stroke.raster_id)
        return bool(asset is not None and self._restore_session(asset.surface, stroke))

    def _matching_session(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
    ) -> _CloneRasterSession | None:
        """Return the active clone session only for its exact target instance."""
        session = self._session
        if session is None:
            return None
        stroke = session.stroke
        if stroke.scene_id != scene.scene_id or stroke.layer_id != layer.layer_id:
            return None
        return session

    def _asset(self, layer: LayerDescriptor) -> EditableRasterAsset | None:
        """Resolve authoritative color storage for one layer descriptor."""
        source = layer.source
        return (
            None
            if not isinstance(source, ProjectResourceReference)
            else self._assets.get(source.resource_id)
        )

    def _resource_revision(self, resource_id: uuid.UUID) -> int | None:
        """Return one project resource revision without exposing its store."""
        record = self._assets.resources.get(resource_id)
        return None if record is None else record.revision
