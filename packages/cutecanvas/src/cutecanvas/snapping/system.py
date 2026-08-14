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

"""Focused construction and lifecycle boundary for editor snapping."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QApplication

from cutecanvas.scene.layer_geometry import LayerGeometryResolver
from cutecanvas.selection import PixelSelectionService
from qpane.sdk.scene import SceneDescriptor

from .authoring import AuthoringSnapCoordinator
from .candidates import SnapCandidateProvider
from .configuration import SnapConfiguration
from .edge_candidates import OrientedEdgeCandidateProvider
from .edge_model import SnapGuideValue
from .feedback import SnapGuideFeedback
from .movement import MovementSnapCoordinator
from .scale import scene_units_per_device_pixel
from .transform import TransformSnapCoordinator


@dataclass(frozen=True, slots=True)
class SnappingSubsystem:
    """Group focused snapping owners behind one editor lifecycle boundary."""

    configuration: SnapConfiguration
    candidates: SnapCandidateProvider
    oriented_candidates: OrientedEdgeCandidateProvider
    feedback: SnapGuideFeedback
    movement: MovementSnapCoordinator
    authoring: AuthoringSnapCoordinator
    transform: TransformSnapCoordinator

    @classmethod
    def create(
        cls,
        *,
        active_scene: Callable[[], SceneDescriptor | None],
        geometry: LayerGeometryResolver,
        pixel_selection: PixelSelectionService,
        panel_to_scene: Callable[[QPointF], QPointF | None],
        scene_to_panel: Callable[[QPointF], QPointF | None],
        viewport_zoom: Callable[[], float],
        changed: Callable[[], None],
    ) -> SnappingSubsystem:
        """Construct the policy, target, feedback, and session owners."""
        configuration = SnapConfiguration(changed)
        candidates = SnapCandidateProvider(
            active_scene=active_scene,
            geometry=geometry,
            pixel_selection=pixel_selection,
            configuration=configuration,
        )
        oriented_candidates = OrientedEdgeCandidateProvider(
            active_scene=active_scene,
            geometry=geometry,
            configuration=configuration,
        )
        feedback = SnapGuideFeedback(changed)
        scale = lambda: scene_units_per_device_pixel(viewport_zoom())
        suppressed = lambda: bool(
            QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier
        )
        movement = MovementSnapCoordinator(
            candidates=candidates,
            configuration=configuration,
            feedback=feedback,
            scene_units_per_device_pixel=scale,
            suppressed=suppressed,
        )
        authoring = AuthoringSnapCoordinator(
            candidates=candidates,
            configuration=configuration,
            feedback=feedback,
            panel_to_scene=panel_to_scene,
            scene_to_panel=scene_to_panel,
            scene_units_per_device_pixel=scale,
            suppressed=suppressed,
        )
        transform = TransformSnapCoordinator(
            candidates=candidates,
            oriented_candidates=oriented_candidates,
            configuration=configuration,
            feedback=feedback,
            movement=movement,
            scene_units_per_device_pixel=scale,
            suppressed=suppressed,
        )
        return cls(
            configuration,
            candidates,
            oriented_candidates,
            feedback,
            movement,
            authoring,
            transform,
        )

    @property
    def guides(self) -> tuple[SnapGuideValue, ...]:
        """Return the current shared Smart Guide presentation."""
        return self.feedback.guides

    def clear_authoring(self) -> bool:
        """Clear authoring state without disturbing an active Move operation."""
        return self.authoring.clear()

    def clear_interactions(self) -> bool:
        """Clear every gesture session and transient Smart Guide."""
        transform_changed = self.transform.clear()
        movement_changed = self.movement.clear()
        authoring_changed = self.authoring.clear()
        return transform_changed or movement_changed or authoring_changed

    def clear_feedback(self) -> bool:
        """Clear transient guide presentation after authoritative context changes."""
        return self.feedback.clear()
