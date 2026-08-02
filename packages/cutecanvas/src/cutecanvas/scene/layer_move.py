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

"""Multi-layer translation sessions for the Move tool."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF
from qpane.sdk.scene import LayerTransform, SceneDescriptor, TransformLocalBounds

from .layer_geometry import LayerGeometryResolver
from .layer_selection import SceneLayerSelectionController
from .movement_mutations import LayerMovementMutationOwner, LayerMovementValue
from .mutations import SceneMutationResult
from .transform_preview import LayerTransformPreview, SceneLayerTransformPreview
from .transform_session import LayerTransformBoxState


@dataclass(frozen=True, slots=True)
class LayerMoveTarget:
    """Retain one selected layer's durable translation base and scene bounds."""

    layer_id: uuid.UUID
    initial_transform: LayerTransform
    scene_bounds: QRectF

    def __post_init__(self) -> None:
        """Detach mutable rectangle geometry."""
        object.__setattr__(self, "scene_bounds", QRectF(self.scene_bounds))


@dataclass(frozen=True, slots=True)
class LayerMoveSession:
    """Retain one coherent selected-layer translation gesture."""

    scene_id: uuid.UUID
    origin: QPointF
    targets: tuple[LayerMoveTarget, ...]

    def __post_init__(self) -> None:
        """Detach mutable pointer geometry."""
        object.__setattr__(self, "origin", QPointF(self.origin))


class SceneLayerMoveController:
    """Own transient and durable translation for the selected layer set."""

    def __init__(
        self,
        *,
        selection: SceneLayerSelectionController,
        preview: SceneLayerTransformPreview,
        mutations: LayerMovementMutationOwner,
        geometry: LayerGeometryResolver,
        scene_provider: Callable[[], SceneDescriptor | None],
    ) -> None:
        """Bind selected identities, geometry, preview, and mutation owners."""
        self._selection = selection
        self._preview = preview
        self._mutations = mutations
        self._geometry = geometry
        self._scene_provider = scene_provider
        self._session: LayerMoveSession | None = None

    @property
    def active(self) -> bool:
        """Return whether a layer-set move owns pointer input."""
        return self._session is not None

    def begin(self, scene_point: QPointF) -> bool:
        """Begin translating every movable member of the current selection."""
        scene = self._scene_provider()
        active = self._selection.current
        if scene is None or active is None or active.scene_id != scene.scene_id:
            return False
        targets = self._resolve_targets(scene)
        if not targets:
            return False
        self.cancel()
        self._session = LayerMoveSession(scene.scene_id, scene_point, targets)
        return True

    def box_state(self) -> LayerTransformBoxState | None:
        """Return the content-tight union used by movement snapping."""
        session = self._session
        if session is None:
            return None
        bounds = QRectF(session.targets[0].scene_bounds)
        for target in session.targets[1:]:
            bounds = bounds.united(target.scene_bounds)
        active = self._selection.current
        primary_layer_id = (
            active.layer_id
            if active is not None
            and any(target.layer_id == active.layer_id for target in session.targets)
            else session.targets[-1].layer_id
        )
        first_target = session.targets[0]
        preview_transform = self._preview.transform_for(
            session.scene_id,
            first_target.layer_id,
        )
        translation = LayerTransform()
        if preview_transform is not None:
            translation = LayerTransform(
                dx=preview_transform.dx - first_target.initial_transform.dx,
                dy=preview_transform.dy - first_target.initial_transform.dy,
            )
        return LayerTransformBoxState(
            session.scene_id,
            primary_layer_id,
            TransformLocalBounds(
                bounds.x(),
                bounds.y(),
                bounds.width(),
                bounds.height(),
            ),
            translation,
            True,
            tuple(target.layer_id for target in session.targets),
        )

    def update(self, scene_point: QPointF) -> bool:
        """Publish one coherent preview for the current translation delta."""
        session = self._session
        if session is None:
            return False
        delta = scene_point - session.origin
        return self._preview.set_many(
            tuple(
                LayerTransformPreview(
                    session.scene_id,
                    target.layer_id,
                    target.initial_transform.translated(delta.x(), delta.y()),
                )
                for target in session.targets
            )
        )

    def finish(self, scene_point: QPointF) -> SceneMutationResult | None:
        """Commit the final translation atomically and retire its preview."""
        session = self._session
        if session is None:
            return None
        self.update(scene_point)
        previews = self._preview.previews
        result = self._mutations.commit(
            session.scene_id,
            tuple(
                LayerMovementValue(preview.layer_id, preview.transform)
                for preview in previews
            ),
        )
        self._session = None
        self._preview.clear()
        return result

    def cancel(self) -> bool:
        """Discard the active move and every associated preview."""
        had_session = self._session is not None
        self._session = None
        return self._preview.clear() or had_session

    def suspend(self) -> bool:
        """Cancel layer movement when another tool takes input ownership."""
        return self.cancel()

    def nudge(self, delta_x: float, delta_y: float) -> SceneMutationResult | None:
        """Commit one atomic keyboard translation for selected movable layers."""
        scene = self._scene_provider()
        if scene is None:
            return None
        targets = self._resolve_targets(scene)
        if not targets:
            return None
        return self._mutations.commit(
            scene.scene_id,
            tuple(
                LayerMovementValue(
                    target.layer_id,
                    target.initial_transform.translated(delta_x, delta_y),
                )
                for target in targets
            ),
        )

    def synchronize_scene(self, scene: SceneDescriptor | None) -> bool:
        """Discard a move whose selected targets no longer belong to the scene."""
        session = self._session
        if session is None:
            return False
        valid_ids = (
            set() if scene is None else {layer.layer_id for layer in scene.layers}
        )
        if (
            scene is not None
            and scene.scene_id == session.scene_id
            and all(target.layer_id in valid_ids for target in session.targets)
        ):
            return False
        return self.cancel()

    def _resolve_targets(self, scene: SceneDescriptor) -> tuple[LayerMoveTarget, ...]:
        """Resolve selected movable layers in stable selection order."""
        descriptors = {layer.layer_id: layer for layer in scene.layers}
        targets = []
        for selected in self._selection.selected:
            layer = descriptors.get(selected.layer_id)
            if (
                selected.scene_id != scene.scene_id
                or layer is None
                or not layer.interaction.selectable
                or not layer.interaction.movable
                or layer.transform is None
            ):
                continue
            local_bounds = self._geometry.resolved_local_bounds(layer)
            if local_bounds is None:
                continue
            targets.append(
                LayerMoveTarget(
                    layer.layer_id,
                    layer.transform,
                    layer.transform.map_rect(local_bounds),
                )
            )
        return tuple(targets)
