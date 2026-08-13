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

"""Shared stationary-target collection for editor snapping gestures."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from cutecanvas.scene.layer_geometry import LayerGeometryResolver
from cutecanvas.selection import PixelSelectionService
from PySide6.QtCore import QRectF
from qpane.sdk.scene import SceneDescriptor

from .configuration import SnapConfiguration, SnapPolicy
from .model import SnapCandidate, SnapGrid, bounds_candidates


@dataclass(frozen=True, slots=True)
class SnapTargetSnapshot:
    """Freeze one scene's configured stationary targets for a gesture."""

    scene_id: uuid.UUID
    candidates: tuple[SnapCandidate, ...]
    grid: SnapGrid | None


class SnapCandidateProvider:
    """Collect configured scene targets once at gesture start."""

    def __init__(
        self,
        *,
        active_scene: Callable[[], SceneDescriptor | None],
        geometry: LayerGeometryResolver,
        pixel_selection: PixelSelectionService,
        configuration: SnapConfiguration,
    ) -> None:
        """Bind authoritative scene geometry, selection, and snap policy."""
        self._active_scene = active_scene
        self._geometry = geometry
        self._pixel_selection = pixel_selection
        self._configuration = configuration

    def capture(
        self,
        *,
        excluded_layer_id: uuid.UUID | None = None,
        excluded_bounds: QRectF | None = None,
        excluded_layer_ids: tuple[uuid.UUID, ...] = (),
        exclude_selection: bool = False,
    ) -> SnapTargetSnapshot | None:
        """Return one immutable target set under the current policy."""
        scene = self._active_scene()
        policy = self._configuration.policy
        if scene is None or not policy.enabled:
            return None
        composition_bounds = QRectF(
            scene.bounds.x,
            scene.bounds.y,
            scene.bounds.width,
            scene.bounds.height,
        )
        candidates: list[SnapCandidate] = []
        if policy.canvas:
            candidates.extend(
                bounds_candidates(
                    "composition",
                    composition_bounds,
                    priority=20,
                    cross_feature_center=True,
                )
            )
        if policy.layers:
            excluded = frozenset(excluded_layer_ids)
            if excluded_layer_id is not None:
                excluded = excluded | {excluded_layer_id}
            candidates.extend(self._layer_candidates(scene, excluded))
        self._append_selection_candidates(
            candidates,
            scene,
            policy,
            excluded_bounds,
            exclude_selection,
        )
        if policy.guides:
            candidates.extend(self._configuration.guide_candidates(composition_bounds))
        grid = (
            self._configuration.grid_model(composition_bounds) if policy.grid else None
        )
        return SnapTargetSnapshot(scene.scene_id, tuple(candidates), grid)

    def _layer_candidates(
        self,
        scene: SceneDescriptor,
        excluded_layer_ids: frozenset[uuid.UUID],
    ) -> tuple[SnapCandidate, ...]:
        """Return content-tight targets for visible scene layers."""
        candidates: list[SnapCandidate] = []
        for layer in scene.layers:
            if (
                not layer.visible
                or layer.layer_id in excluded_layer_ids
                or layer.transform is None
            ):
                continue
            local_bounds = self._geometry.resolved_local_bounds(layer)
            if local_bounds is None:
                continue
            candidates.extend(
                bounds_candidates(
                    str(layer.layer_id),
                    layer.transform.map_rect(local_bounds),
                    priority=10,
                )
            )
        return tuple(candidates)

    def _append_selection_candidates(
        self,
        candidates: list[SnapCandidate],
        scene: SceneDescriptor,
        policy: SnapPolicy,
        excluded_bounds: QRectF | None,
        exclude_selection: bool,
    ) -> None:
        """Append current pixel-selection bounds unless they are the moving source."""
        selection = self._pixel_selection.state(scene.scene_id).coverage
        if (
            exclude_selection
            or not policy.selections
            or selection is None
            or selection.bounds is None
        ):
            return
        bounds = selection.bounds
        selection_bounds = QRectF(bounds.x, bounds.y, bounds.width, bounds.height)
        if excluded_bounds is not None and selection_bounds == excluded_bounds:
            return
        candidates.extend(bounds_candidates("selection", selection_bounds, priority=15))
