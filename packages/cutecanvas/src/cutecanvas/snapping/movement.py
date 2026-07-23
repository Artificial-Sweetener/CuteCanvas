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
"""Movement-session adapter for shared content-tight editor snapping."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF
from qpane.sdk.scene import SceneDescriptor

from cutecanvas.scene.layer_geometry import LayerGeometryResolver
from cutecanvas.scene.transform_session import LayerTransformBoxState
from cutecanvas.selection import PixelSelectionService

from .configuration import SnapConfiguration
from .engine import SnapEngine, SnapSession
from .model import SnapCandidate, SnapGuide, bounds_candidates


class MovementSnapCoordinator:
    """Build and resolve one shared snap session for any movable editor target."""

    def __init__(
        self,
        *,
        active_scene: Callable[[], SceneDescriptor | None],
        geometry: LayerGeometryResolver,
        pixel_selection: PixelSelectionService,
        configuration: SnapConfiguration,
        scene_units_per_device_pixel: Callable[[], float],
        suppressed: Callable[[], bool],
        changed: Callable[[], None],
    ) -> None:
        """Bind scene geometry, selection, scale, and overlay publication."""
        self._active_scene = active_scene
        self._geometry = geometry
        self._pixel_selection = pixel_selection
        self._configuration = configuration
        self._scene_units_per_device_pixel = scene_units_per_device_pixel
        self._suppressed = suppressed
        self._changed = changed
        self._engine = SnapEngine()
        self._session: SnapSession | None = None
        self._origin = QPointF()
        self._guides: tuple[SnapGuide, ...] = ()

    @property
    def guides(self) -> tuple[SnapGuide, ...]:
        """Return smart guides for the latest resolved movement update."""
        return self._guides

    def begin(self, box: LayerTransformBoxState | None, origin: QPointF) -> bool:
        """Begin snapping for one layer or floating-pixel transform box."""
        scene = self._active_scene()
        policy = self._configuration.policy
        if (
            scene is None
            or box is None
            or scene.scene_id != box.scene_id
            or not policy.enabled
        ):
            self.clear()
            return False
        source_bounds = box.transform.map_rect(
            QRectF(box.bounds.x, box.bounds.y, box.bounds.width, box.bounds.height)
        )
        composition_bounds = QRectF(
            scene.bounds.x,
            scene.bounds.y,
            scene.bounds.width,
            scene.bounds.height,
        )
        candidates = []
        if policy.canvas:
            candidates.extend(
                bounds_candidates("composition", composition_bounds, priority=20)
            )
        if policy.layers:
            candidates.extend(self._layer_candidates(scene, box.layer_id))
        selection = self._pixel_selection.state(scene.scene_id).coverage
        if policy.selections and selection is not None and selection.bounds is not None:
            bounds = selection.bounds
            selection_bounds = QRectF(
                bounds.x,
                bounds.y,
                bounds.width,
                bounds.height,
            )
            if selection_bounds != source_bounds:
                candidates.extend(
                    bounds_candidates(
                        "selection",
                        selection_bounds,
                        priority=15,
                    )
                )
        if policy.guides:
            candidates.extend(self._configuration.guide_candidates(composition_bounds))
        grid = (
            self._configuration.grid_model(composition_bounds) if policy.grid else None
        )
        self._session = self._engine.begin(
            str(box.layer_id),
            source_bounds,
            tuple(candidates),
            threshold_device_pixels=policy.threshold_device_pixels,
            release_device_pixels=policy.release_device_pixels,
            grid=grid,
        )
        self._origin = QPointF(origin)
        self._set_guides(())
        return True

    def _layer_candidates(
        self,
        scene: SceneDescriptor,
        moving_layer_id: object,
    ) -> tuple[SnapCandidate, ...]:
        """Return content-tight candidates for other visible scene layers."""
        candidates = []
        for layer in scene.layers:
            if (
                not layer.visible
                or layer.layer_id == moving_layer_id
                or layer.transform is None
            ):
                continue
            local = self._geometry.resolved_local_bounds(layer)
            if local is None:
                continue
            mapped = layer.transform.map_rect(local)
            candidates.extend(
                bounds_candidates(
                    str(layer.layer_id),
                    mapped,
                    priority=10,
                )
            )
        return tuple(candidates)

    def resolve(self, scene_point: QPointF, *, suppressed: bool = False) -> QPointF:
        """Return a corrected scene point for the active movement owner."""
        if self._session is None:
            return QPointF(scene_point)
        result = self._session.resolve(
            scene_point - self._origin,
            scene_units_per_device_pixel=max(
                1e-9, float(self._scene_units_per_device_pixel())
            ),
            suppressed=suppressed or self._suppressed(),
        )
        self._set_guides(result.guides)
        return self._origin + result.delta

    def clear(self) -> bool:
        """End snapping and remove any smart-guide presentation."""
        had_state = self._session is not None or bool(self._guides)
        self._session = None
        self._origin = QPointF()
        self._set_guides(())
        return had_state

    def _set_guides(self, guides: tuple[SnapGuide, ...]) -> None:
        """Publish smart-guide changes only when presentation differs."""
        if guides == self._guides:
            return
        self._guides = guides
        self._changed()
