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
from cutecanvas.snapping.edge_candidates import OrientedEdgeCandidateProvider
from cutecanvas.snapping.feedback import SnapGuideFeedback

from .session_coordination import EditSessionCoordinator
from .shared_edge_geometry import SharedEdgeSeam
from .shared_edge_handle_resolution import SharedEdgeHandleResolver
from .shared_edge_history import SharedEdgeProvisionalSession
from .shared_edge_index import SharedEdgeDiscoveryIndex
from .shared_edge_pivot import SharedEdgeHandle, SharedEdgePivot
from .shared_edge_presentation import (
    SharedEdgePresentation,
    SharedEdgePresentationProjector,
)
from .shared_edge_publication import SharedEdgeMappingPublication
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
        sessions: EditSessionCoordinator,
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
        self._sessions = sessions
        self._feedback = feedback
        self._panel_to_scene = panel_to_scene
        self._scene_units_per_device_pixel = scene_units_per_device_pixel
        self._suppressed = suppressed
        self._presentation_changed = presentation_changed
        self._transform_preview_changed = transform_preview_changed
        self._publication = SharedEdgeMappingPublication(
            active_scene=active_scene,
            preview=preview,
            mutations=mutations,
            preview_changed=transform_preview_changed,
            committed=committed,
        )
        self._projector = SharedEdgePresentationProjector(
            scene_to_panel=scene_to_panel,
        )
        self._discovery = SharedEdgeDiscoveryIndex(
            candidates=candidates,
            preview=preview,
            scale=self._scale,
        )
        self._handles = SharedEdgeHandleResolver(
            active_scene=active_scene,
            discovery=self._discovery,
            scale=self._scale,
        )
        self._seam: SharedEdgeSeam | None = None
        self._handle: SharedEdgeHandle | None = None
        self._pivot: SharedEdgePivot | None = None
        self._session: SharedEdgeGestureSession | None = None
        self._provisional: SharedEdgeProvisionalSession | None = None

    @property
    def active(self) -> bool:
        """Return whether the interaction owns a pointer gesture."""
        return self._session is not None

    def presentation(self) -> SharedEdgePresentation | None:
        """Return all discoverable handles and current focused geometry."""
        scene = self._active_scene()
        if scene is None:
            return None
        discovery = self._discovery.get(scene)
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
        seam = None if scene_point is None else self._discover(scene_point)
        handle = (
            None
            if seam is None or scene_point is None
            else self._handles.handle_at(
                seam,
                scene_point,
            )
        )
        pivot = self._handles.pivot_for(seam, handle)
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
        if self.active:
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
        participant_ids = frozenset(
            participant.layer_id for participant in seam.participants
        )
        if (
            self._provisional is not None
            and participant_ids != self._provisional.layer_ids
        ):
            return False
        if self._provisional is None:
            base = tuple(
                LayerMappingValue(
                    participant.layer_id,
                    participant.initial_mapping,
                )
                for participant in seam.participants
            )
            self._provisional = SharedEdgeProvisionalSession.begin(
                sessions=self._sessions,
                scene_id=seam.scene_id,
                base=base,
                restore=self._publication.restore,
                commit=self._publication.commit,
                closed=self._close_provisional,
            )
            if self._provisional is None:
                return False
        scene = self._active_scene()
        if scene is None:
            return False
        excluded = tuple(participant.layer_id for participant in seam.participants)
        targets = self._candidates.capture_scene(
            self._preview.process_scene(scene),
            excluded_layer_ids=excluded,
        )
        scale = self._scale()
        self._session = SharedEdgeGestureSession(
            seam=seam,
            handle=handle,
            pivot=self._pivot,
            origin=origin,
            targets=targets,
            scene_units_per_device_pixel=scale,
        )
        self._provisional.begin_gesture()
        self._feedback.clear()
        self._presentation_changed()
        return True

    def update(self, panel_point: QPointF) -> bool:
        """Publish every mapping preview from the active constrained handle."""
        seam = self._valid_active_seam()
        scene = self._active_scene()
        session = self._session
        scene_point = self._panel_to_scene(panel_point)
        if (
            seam is None
            or scene is None
            or scene.scene_id != seam.scene_id
            or session is None
            or scene_point is None
        ):
            return False
        update = session.resolve(
            scene_point,
            scene_units_per_device_pixel=self._scale(),
            suppressed=self._suppressed(),
        )
        if update is None:
            return False
        changed = self._preview.set_many(
            scene,
            tuple(
                LayerMappingPreview(seam.scene_id, layer_id, mapping)
                for layer_id, mapping in update.values
            ),
        )
        self._feedback.publish(update.guides)
        if changed:
            self._transform_preview_changed()
        return True

    def finish(self, panel_point: QPointF) -> bool:
        """Resolve the final pointer and retain one coupled checkpoint."""
        if not self.update(panel_point):
            if self._provisional is not None:
                self._provisional.suspend()
            self._clear_gesture()
            return False
        provisional = self._provisional
        if provisional is None:
            return False
        values = self._publication.settled_values(provisional.layer_ids)
        if values is None:
            provisional.suspend()
            self._clear_gesture()
            return False
        label = (
            "Move Shared Edge"
            if self._handle is SharedEdgeHandle.MIDDLE
            else "Move Shared Edge Point"
        )
        changed = provisional.settle(values, label)
        self._clear_gesture()
        self._discovery.invalidate()
        self._presentation_changed()
        return changed

    def apply(self) -> bool:
        """Commit every retained seam gesture as one atomic document edit."""
        return self._provisional is not None and self._provisional.apply()

    def suspend(self) -> bool:
        """Release direct seam input while retaining settled checkpoints."""
        provisional = self._provisional
        if provisional is None:
            return False
        changed = provisional.suspend()
        self._clear_gesture()
        self._presentation_changed()
        return changed

    def cancel(self) -> bool:
        """Discard every preview and all gesture or hover state."""
        if self._provisional is not None:
            return self._provisional.cancel()
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
        session_scene_id = (
            None if self._provisional is None else self._provisional.scene_id
        )
        seam = self._seam
        expected_scene_id = session_scene_id or (
            None if seam is None else seam.scene_id
        )
        if expected_scene_id is None or (
            scene is not None and scene.scene_id == expected_scene_id
        ):
            self._discovery.invalidate()
            return False
        return self.cancel()

    def _discover(self, scene_point: QPointF) -> SharedEdgeSeam | None:
        """Use one cached scene-revision index for repeated hover updates."""
        scene = self._active_scene()
        if scene is None:
            return None
        discovery = self._discovery.get(scene)
        return None if discovery is None else discovery.seam_at(scene_point)

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
        self._discovery.invalidate()

    def _clear_gesture(self) -> None:
        """Release pointer-specific snap state without resolving the edit."""
        self._feedback.clear()
        if self._session is not None:
            self._session.clear()
        self._session = None

    def _close_provisional(self) -> None:
        """Clear preview and interaction state after apply or cancellation."""
        self._provisional = None
        self._publication.clear()
        self._clear_transient(clear_preview=False)
        self._presentation_changed()

    def _scale(self) -> float:
        """Return a positive current scene-unit size for one device pixel."""
        return max(1e-9, float(self._scene_units_per_device_pixel()))

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
