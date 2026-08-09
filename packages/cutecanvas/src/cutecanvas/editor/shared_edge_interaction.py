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

"""Panel interaction and atomic publication for shared-edge resizing."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPointF
from qpane.sdk.scene import SceneDescriptor

from cutecanvas.scene.mapping_mutations import (
    LayerMappingMutationOwner,
    LayerMappingValue,
)
from cutecanvas.scene.mapping_preview import (
    LayerMappingPreview,
    SceneLayerMappingPreview,
)
from cutecanvas.scene.mutations import SceneMutationStatus
from cutecanvas.snapping.edge_candidates import OrientedEdgeCandidateProvider
from cutecanvas.snapping.edge_index import OrientedEdgeIndex
from cutecanvas.snapping.feedback import SnapGuideFeedback

from .shared_edge_discovery import SharedEdgeDiscovery
from .shared_edge_geometry import SharedEdgeSeam
from .shared_edge_pivot import SharedEdgeHandle, SharedEdgePivot
from .shared_edge_presentation import (
    SharedEdgePresentation,
    SharedEdgePresentationProjector,
)
from .shared_edge_session import SharedEdgeGestureSession


class SharedEdgeResizeInteraction:
    """Own inferred-seam hover, coupled preview, and atomic commit lifecycle."""

    def __init__(
        self,
        *,
        active_scene: Callable[[], SceneDescriptor | None],
        candidates: OrientedEdgeCandidateProvider,
        preview: SceneLayerMappingPreview,
        mutations: LayerMappingMutationOwner,
        feedback: SnapGuideFeedback,
        panel_to_scene: Callable[[QPointF], QPointF | None],
        scene_to_panel: Callable[[QPointF], QPointF | None],
        scene_units_per_device_pixel: Callable[[], float],
        suppressed: Callable[[], bool],
        presentation_changed: Callable[[], None],
        transform_preview_changed: Callable[[], None],
        committed: Callable[[], None],
    ) -> None:
        """Bind exact geometry, preview, mutation, and presentation owners."""
        self._active_scene = active_scene
        self._candidates = candidates
        self._preview = preview
        self._mutations = mutations
        self._feedback = feedback
        self._panel_to_scene = panel_to_scene
        self._scene_units_per_device_pixel = scene_units_per_device_pixel
        self._suppressed = suppressed
        self._presentation_changed = presentation_changed
        self._transform_preview_changed = transform_preview_changed
        self._committed = committed
        self._projector = SharedEdgePresentationProjector(
            scene_to_panel=scene_to_panel,
        )
        self._cache_key: tuple[int, float] | None = None
        self._discovery: SharedEdgeDiscovery | None = None
        self._seam: SharedEdgeSeam | None = None
        self._handle: SharedEdgeHandle | None = None
        self._pivot: SharedEdgePivot | None = None
        self._session: SharedEdgeGestureSession | None = None

    @property
    def active(self) -> bool:
        """Return whether the interaction owns a pointer gesture."""
        return self._session is not None

    def presentation(self) -> SharedEdgePresentation | None:
        """Return all discoverable handles and current focused geometry."""
        scene = self._active_scene()
        if scene is None:
            return None
        discovery = self._ensure_discovery(scene)
        seams = () if discovery is None else discovery.seams()
        return self._projector.project(
            seams,
            focused=self._seam,
            focused_points=self._focused_points(),
            focused_handle=self._handle,
            pivot_for=(
                (lambda _seam: (None, None)) if discovery is None else discovery.pivots
            ),
            active=self.active,
        )

    def update_hover(self, panel_point: QPointF) -> bool:
        """Discover and publish the eligible seam beneath one panel point."""
        if self.active:
            return False
        scene_point = self._panel_to_scene(panel_point)
        seam = (
            None
            if scene_point is None or self._preview.previews
            else self._discover(scene_point)
        )
        handle = (
            None
            if seam is None or scene_point is None
            else self._handle_at(
                seam,
                scene_point,
            )
        )
        pivot = self._pivot_for(seam, handle)
        if seam == self._seam and handle is self._handle and pivot == self._pivot:
            return False
        self._seam = seam
        self._handle = handle
        self._pivot = pivot
        self._presentation_changed()
        return True

    def clear_hover(self) -> bool:
        """Remove inactive seam feedback."""
        if self.active or self._seam is None:
            return False
        self._seam = None
        self._handle = None
        self._pivot = None
        self._presentation_changed()
        return True

    def begin(self, panel_point: QPointF) -> bool:
        """Begin a coupled gesture from the seam under ``panel_point``."""
        if self.active or self._preview.previews:
            return False
        self.update_hover(panel_point)
        seam = self._seam
        handle = self._handle
        origin = self._panel_to_scene(panel_point)
        if (
            seam is None
            or handle is None
            or origin is None
            or (
                handle is SharedEdgeHandle.MIDDLE
                and not seam.parallel_translation_enabled
            )
            or (handle is not SharedEdgeHandle.MIDDLE and self._pivot is None)
        ):
            return False
        excluded = tuple(participant.layer_id for participant in seam.participants)
        targets = self._candidates.capture(excluded_layer_ids=excluded)
        scale = self._scale()
        self._session = SharedEdgeGestureSession(
            seam=seam,
            handle=handle,
            pivot=self._pivot,
            origin=origin,
            targets=targets,
            scene_units_per_device_pixel=scale,
        )
        self._feedback.clear()
        self._presentation_changed()
        return True

    def update(self, panel_point: QPointF) -> bool:
        """Publish every mapping preview from the active constrained handle."""
        seam = self._valid_active_seam()
        session = self._session
        scene_point = self._panel_to_scene(panel_point)
        if seam is None or session is None or scene_point is None:
            return False
        update = session.resolve(
            scene_point,
            scene_units_per_device_pixel=self._scale(),
            suppressed=self._suppressed(),
        )
        if update is None:
            return False
        changed = self._preview.set_many(
            tuple(
                LayerMappingPreview(seam.scene_id, layer_id, mapping)
                for layer_id, mapping in update.values
            )
        )
        self._feedback.publish(update.guides)
        if changed:
            self._transform_preview_changed()
        return True

    def finish(self, panel_point: QPointF) -> bool:
        """Resolve the final pointer and commit all transforms atomically."""
        if not self.update(panel_point):
            return self.cancel()
        seam = self._seam
        if seam is None:
            return self.cancel()
        values = tuple(
            LayerMappingValue(preview.layer_id, preview.mapping)
            for preview in self._preview.previews
        )
        result = self._mutations.commit(seam.scene_id, values)
        applied = result.status in {
            SceneMutationStatus.APPLIED,
            SceneMutationStatus.UNCHANGED,
        }
        self._clear_transient()
        if applied and result.status is SceneMutationStatus.APPLIED:
            self._committed()
        else:
            self._transform_preview_changed()
        return applied

    def cancel(self) -> bool:
        """Discard every preview and all gesture or hover state."""
        changed = self._seam is not None or self._session is not None
        preview_changed = self._preview.clear()
        self._clear_transient(clear_preview=False)
        if preview_changed:
            self._transform_preview_changed()
        elif changed:
            self._presentation_changed()
        return changed or preview_changed

    def synchronize_scene(self, scene: SceneDescriptor | None) -> bool:
        """Clear transient state when the authoritative scene changes."""
        seam = self._seam
        if seam is None or (scene is not None and scene.scene_id == seam.scene_id):
            self._cache_key = None
            self._discovery = None
            return False
        return self.cancel()

    def _discover(self, scene_point: QPointF) -> SharedEdgeSeam | None:
        """Use one cached scene-revision index for repeated hover updates."""
        scene = self._active_scene()
        if scene is None:
            return None
        discovery = self._ensure_discovery(scene)
        return None if discovery is None else discovery.seam_at(scene_point)

    def _ensure_discovery(
        self,
        scene: SceneDescriptor,
    ) -> SharedEdgeDiscovery | None:
        """Return the cached discovery snapshot for one scene revision and scale."""
        scale = self._scale()
        key = id(scene), scale
        if key != self._cache_key:
            targets = self._candidates.capture(layers_only=True)
            self._discovery = (
                None
                if targets is None or targets.scene_id != scene.scene_id
                else SharedEdgeDiscovery(
                    scene,
                    OrientedEdgeIndex.build(
                        targets.edges,
                        scene_units_per_device_pixel=scale,
                    ),
                    scene_units_per_device_pixel=scale,
                    boundary_for=self._candidates.layer_boundary,
                )
            )
            self._cache_key = key
        return self._discovery

    def _valid_active_seam(self) -> SharedEdgeSeam | None:
        """Return the active seam while its authoritative scene remains current."""
        seam = self._seam
        scene = self._active_scene()
        if seam is None or scene is None or scene.scene_id != seam.scene_id:
            self.cancel()
            return None
        return seam

    def _clear_transient(self, *, clear_preview: bool = True) -> None:
        """Clear the complete interaction state without publishing callbacks."""
        if clear_preview:
            self._preview.clear()
        self._feedback.clear()
        self._seam = None
        self._handle = None
        self._pivot = None
        if self._session is not None:
            self._session.clear()
        self._session = None
        self._cache_key = None
        self._discovery = None

    def _scale(self) -> float:
        """Return a positive current scene-unit size for one device pixel."""
        return max(1e-9, float(self._scene_units_per_device_pixel()))

    def _handle_at(
        self,
        seam: SharedEdgeSeam,
        scene_point: QPointF,
    ) -> SharedEdgeHandle:
        """Resolve endpoint handles ahead of the parallel-resize seam body."""
        radius = 8.0 * self._scale()
        distances = (
            (_point_distance(scene_point, seam.start), SharedEdgeHandle.START),
            (_point_distance(scene_point, seam.end), SharedEdgeHandle.END),
        )
        nearest_distance, nearest_handle = min(distances, key=lambda value: value[0])
        return nearest_handle if nearest_distance <= radius else SharedEdgeHandle.MIDDLE

    def _pivot_for(
        self,
        seam: SharedEdgeSeam | None,
        handle: SharedEdgeHandle | None,
    ) -> SharedEdgePivot | None:
        """Return the frozen endpoint constraint associated with one hover."""
        if seam is None or handle is None or handle is SharedEdgeHandle.MIDDLE:
            return None
        scene = self._active_scene()
        if scene is None:
            return None
        discovery = self._ensure_discovery(scene)
        if discovery is None:
            return None
        start, end = discovery.pivots(seam)
        return start if handle is SharedEdgeHandle.START else end

    def _focused_points(self) -> tuple[QPointF, QPointF] | None:
        """Return current scene endpoints for focused presentation geometry."""
        seam = self._seam
        if seam is None:
            return None
        return (
            (QPointF(seam.start), QPointF(seam.end))
            if self._session is None
            else self._session.points
        )


def _point_distance(first: QPointF, second: QPointF) -> float:
    """Return Euclidean scene distance between two points."""
    delta = first - second
    return QPointF.dotProduct(delta, delta) ** 0.5


__all__ = ["SharedEdgeResizeInteraction"]
