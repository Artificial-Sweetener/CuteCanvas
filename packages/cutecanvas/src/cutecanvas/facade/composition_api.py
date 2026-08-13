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
"""CompositionApi behavior for the CuteCanvas facade."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import replace

from cutecanvas.composition.geometry_policy import LayerGeometryPolicy
from cutecanvas.composition.public_layer_mapping import (
    detached_public_layer_mapping,
    normalize_public_layer_mapping,
)
from cutecanvas.composition.public_policy import (
    internal_document_policy,
    internal_layer_policy,
)
from cutecanvas.types import (
    CompositionPolicy,
    CompositionSnapshot,
    LayerHit,
    LayerPolicy,
    LayerSelectionSnapshot,
    SceneSnapshot,
)
from PySide6.QtCore import (
    QPoint,
    QRectF,
)
from PySide6.QtGui import (
    QImage,
    QTransform,
)
from qpane.sdk.scene import (
    BilinearLayerTransform,
    LayerMapping,
    LayerPlacement,
    PiecewiseLayerTransform,
)


class CompositionApiMixin:
    """Group compositionapi facade behavior."""

    def currentCompositionID(self) -> uuid.UUID | None:
        """Return the active document identity."""
        return self.viewSession().active_composition_id

    def compositionIDs(self) -> list[uuid.UUID]:
        """Return document identities in browser order."""
        return list(self.compositionService().composition_ids())

    def getCompositionSnapshot(self) -> CompositionSnapshot:
        """Return a detached snapshot of every document and layer."""
        return self.compositionService().snapshot(
            active_composition_id=self.viewSession().active_composition_id,
        )

    def createComposition(
        self,
        bounds: QRectF,
        *,
        title: str = "Untitled",
        policy: CompositionPolicy | None = None,
        fit_view: bool = True,
    ) -> uuid.UUID:
        """Create and open an empty composition document.

        Args:
            bounds: Positive scene-space canvas bounds.
            title: Non-empty host-facing document title.
            policy: Optional document-level removal and comparison permissions.
            fit_view: Fit the new canvas in the viewport when True.

        Returns:
            The independent composition UUID.

        Side effects:
            Opens the document and emits composition and scene signals.
        """
        record = self.compositionService().create_composition(
            bounds,
            title=title,
            policy=internal_document_policy(policy or CompositionPolicy()),
        )
        self._emit_composition_changed()
        self._open_composition_record(record, fit_view=fit_view)
        return record.composition_id

    def createCompositionFromImage(
        self,
        image: QImage,
        *,
        title: str | None = None,
        label: str | None = None,
        interaction: LayerPolicy | None = None,
        policy: CompositionPolicy | None = None,
        fit_view: bool = True,
    ) -> uuid.UUID:
        """Create an independent composition from detached image pixels.

        Args:
            image: Non-null raster copied into project resource storage.
            title: Optional document title.
            label: Optional label for the ordinary seeded layer.
            interaction: Host policy for the ordinary seeded layer.
            policy: Optional document-level removal and comparison permissions.
            fit_view: Fit the new canvas in the viewport when True.

        Returns:
            The independent composition UUID.

        Side effects:
            Opens the document and emits composition and scene signals.
        """
        if not isinstance(image, QImage):
            raise TypeError("image must be a QImage")
        if image.isNull():
            raise ValueError("image must not be null")
        if title is not None and not isinstance(title, str):
            raise TypeError("title must be a string or None")
        if label is not None and not isinstance(label, str):
            raise TypeError("label must be a string or None")
        if interaction is not None and not isinstance(
            interaction,
            LayerPolicy,
        ):
            raise TypeError("interaction must be LayerPolicy or None")
        if policy is not None and not isinstance(policy, CompositionPolicy):
            raise TypeError("policy must be CompositionPolicy or None")
        workflow = self._image_documents
        if workflow is None:
            raise RuntimeError("image document workflow is not available")
        result = workflow.create(
            image,
            title=title or "Untitled",
            label=label,
            interaction=internal_layer_policy(
                interaction
                or LayerPolicy(
                    selectable=True,
                    movable=True,
                    pixel_editable=False,
                )
            ),
            policy=internal_document_policy(policy or CompositionPolicy()),
        )
        record = self.compositionService().record(result.document_id)
        self._emit_composition_changed()
        self._open_composition_record(record, fit_view=fit_view)
        return record.composition_id

    def setCompositionPolicy(
        self,
        composition_id: uuid.UUID,
        policy: CompositionPolicy,
    ) -> bool:
        """Replace structural permissions for one composition document.

        Args:
            composition_id: Existing composition identity.
            policy: Host-selected structural permissions.

        Returns:
            True when composition policy changed.

        Side effects:
            Emits composition state when a change occurs.
        """
        if not isinstance(composition_id, uuid.UUID):
            raise TypeError("composition_id must be a UUID")
        if not isinstance(policy, CompositionPolicy):
            raise TypeError("policy must be CompositionPolicy")
        changed = self.compositionService().set_document_policy(
            composition_id,
            internal_document_policy(policy),
        )
        if changed:
            self._emit_composition_changed()
        return changed

    def currentScene(self) -> SceneSnapshot | None:
        """Return the normalized scene snapshot for the active composition."""
        return self._current_scene_snapshot()

    def sceneHitTest(self, panel_pos: QPoint) -> LayerHit | None:
        """Return scene-layer hit metadata for ``panel_pos``."""
        adapter = self._composition_scene_adapter
        if adapter is None:
            return None
        return adapter.hit_from_result(self.view().scene_hit_test(panel_pos))

    def layerTransform(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> QTransform | PiecewiseLayerTransform | BilinearLayerTransform | None:
        """Return one active layer's detached exact local-to-scene transform.

        Args:
            scene_id: Public or resolved identifier for the active scene.
            layer_id: Stable identifier of the layer to inspect.

        Returns:
            A detached exact transform, or None when the layer is unavailable.

        Raises:
            TypeError: If either identifier is not a UUID.
        """
        if not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        current_scene = self.currentScene()
        active_scene = self.sceneMutationCoordinator().active_scene()
        valid_scene_ids = {
            candidate
            for candidate in (
                None if current_scene is None else current_scene.scene_id,
                None if active_scene is None else active_scene.scene_id,
            )
            if candidate is not None
        }
        composition_id = self.currentCompositionID()
        if scene_id not in valid_scene_ids or composition_id is None:
            return None
        instance = self.compositionService().layers.layer(composition_id, layer_id)
        if instance is None:
            return None
        return detached_public_layer_mapping(instance.transform)

    def layerLocalBounds(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> QRectF | None:
        """Return one active layer's detached intrinsic local bounds.

        Args:
            scene_id: Public or resolved identifier for the active scene.
            layer_id: Stable identifier of the layer to inspect.

        Returns:
            Detached source-local bounds, or None when unavailable.

        Raises:
            TypeError: If either identifier is not a UUID.
        """
        if not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        current_scene = self.currentScene()
        active_scene = self.sceneMutationCoordinator().active_scene()
        valid_scene_ids = {
            candidate
            for candidate in (
                None if current_scene is None else current_scene.scene_id,
                None if active_scene is None else active_scene.scene_id,
            )
            if candidate is not None
        }
        if active_scene is None or scene_id not in valid_scene_ids:
            return None
        layer = next(
            (
                candidate
                for candidate in active_scene.layers
                if candidate.layer_id == layer_id
            ),
            None,
        )
        bounds = (
            None
            if layer is None
            else self.layerGeometryResolver().resolved_local_bounds(layer)
        )
        return None if bounds is None else QRectF(bounds)

    def setLayerInteractionPolicy(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        policy: LayerPolicy,
    ) -> bool:
        """Set direct-interaction permissions for an active scene layer.

        Args:
            scene_id: Public or resolved identifier for the active scene.
            layer_id: Stable identifier of the layer to update.
            policy: Selection and movement permissions to apply.

        Returns:
            True when the policy changed.

        Raises:
            TypeError: If identifiers or policy use unsupported types.

        Side effects:
            Refreshes active scene rendering and emits sceneChanged after a change.
        """
        if not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        if not isinstance(policy, LayerPolicy):
            raise TypeError("policy must be LayerPolicy")
        coordinator = self.sceneMutationCoordinator()
        result = coordinator.set_interaction(
            self._resolve_public_scene_id(scene_id),
            layer_id,
            internal_layer_policy(policy),
        )
        if result.changed:
            self.view().invalidate_content_cache()
            self._handle_internal_scene_content_changed()
            self._emit_scene_changed()
        return result.changed

    def layerGeometryPolicy(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> LayerGeometryPolicy | None:
        """Return one layer's manipulation-geometry policy."""
        if not isinstance(scene_id, uuid.UUID) or not isinstance(layer_id, uuid.UUID):
            raise TypeError("scene_id and layer_id must be UUIDs")
        instance = self.compositionService().layers.layer(
            self._resolve_public_scene_id(scene_id),
            layer_id,
        )
        return None if instance is None else instance.geometry

    def setLayerGeometryPolicy(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        policy: LayerGeometryPolicy,
    ) -> bool:
        """Set bounds used by move, transform, snapping, and editor overlays."""
        if not isinstance(scene_id, uuid.UUID) or not isinstance(layer_id, uuid.UUID):
            raise TypeError("scene_id and layer_id must be UUIDs")
        if not isinstance(policy, LayerGeometryPolicy):
            raise TypeError("policy must be LayerGeometryPolicy")
        service = self.compositionService()
        resolved_scene_id = self._resolve_public_scene_id(scene_id)
        instance = service.layers.layer(resolved_scene_id, layer_id)
        if instance is None or not service.layer_edits.replace_instance(
            resolved_scene_id,
            replace(instance, geometry=policy),
        ):
            return False
        self._publish_scene_layer_change()
        return True

    def setLayerPlacement(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        placement: QRectF,
    ) -> bool:
        """Set absolute scene-space placement for a movable active layer.

        Args:
            scene_id: Public or resolved identifier for the active scene.
            layer_id: Stable identifier of the layer to move.
            placement: New scene-space layer rectangle.

        Returns:
            True when placement changed and one history command was recorded.

        Raises:
            TypeError: If identifiers or placement use unsupported types.
            ValueError: If placement dimensions or coordinates are invalid.

        Side effects:
            Refreshes scene rendering and emits scene/history signals after a change.
        """
        if not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        if not isinstance(placement, QRectF):
            raise TypeError("placement must be a QRectF")
        if not self._anchor_floating_pixels_before_edit():
            return False
        resolved_scene_id = self._resolve_public_scene_id(scene_id)
        result = self.sceneMutationCoordinator().set_placement(
            resolved_scene_id,
            layer_id,
            LayerPlacement(
                placement.x(),
                placement.y(),
                placement.width(),
                placement.height(),
            ),
        )
        if result.changed:
            self._publish_scene_layer_change()
        return result.changed

    def setLayerTransform(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        transform: QTransform | LayerMapping,
    ) -> bool:
        """Set one movable active layer's exact local-to-scene mapping.

        Args:
            scene_id: Public or resolved identifier for the active scene.
            layer_id: Stable identifier of the layer to transform.
            transform: Finite, invertible supported layer mapping.

        Returns:
            True when geometry changed and one history command was recorded.

        Raises:
            TypeError: If identifiers or transform use unsupported types.
            ValueError: If the transform is singular or non-finite.

        Side effects:
            Refreshes scene rendering and emits scene/history signals after a change.
        """
        if not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        normalized = normalize_public_layer_mapping(transform)
        if not normalized.is_invertible:
            raise ValueError("transform must be numerically invertible")
        if not self._anchor_floating_pixels_before_edit():
            return False
        result = self.sceneMutationCoordinator().set_transform(
            self._resolve_public_scene_id(scene_id),
            layer_id,
            normalized,
        )
        if result.changed:
            self._publish_scene_layer_change()
        return result.changed

    def setLayerIndex(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        index: int,
    ) -> bool:
        """Move one active layer to a bottom-to-top composition stack index.

        Args:
            scene_id: Public or resolved identifier for the active scene.
            layer_id: Stable identifier of the layer to reorder.
            index: Target render index, where zero is bottommost.

        Returns:
            True when order changed and one history command was recorded.

        Raises:
            TypeError: If identifiers or index use unsupported types.

        Side effects:
            Refreshes scene rendering and composition snapshots after a change.
        """
        if not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        if not isinstance(index, int):
            raise TypeError("index must be an int")
        composition_id = self.currentCompositionID()
        active = self.sceneMutationCoordinator().active_scene()
        resolved_scene_id = self._resolve_public_scene_id(scene_id)
        if (
            active is None
            or composition_id is None
            or active.scene_id != resolved_scene_id
        ):
            return False
        if not self._anchor_floating_pixels_before_edit():
            return False
        changed = self.compositionService().set_layer_index(
            composition_id,
            layer_id,
            index,
        )
        if changed:
            self._refresh_active_scene_content(fit_view=False)
        return changed

    def removeLayer(self, scene_id: uuid.UUID, layer_id: uuid.UUID) -> bool:
        """Remove one policy-enabled layer from the active composition.

        Args:
            scene_id: Public identifier for the active composition scene.
            layer_id: Stable identifier of the layer to remove.

        Returns:
            True when one undoable removal was applied.

        Side effects:
            Refreshes composition state, rendering, selection, and history signals.
        """
        if not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        composition_id = self.currentCompositionID()
        scene = self.currentScene()
        if (
            composition_id is None
            or scene is None
            or scene.scene_id != scene_id
            or not self._anchor_floating_pixels_before_edit()
        ):
            return False
        changed = self.compositionService().remove_layer(
            composition_id,
            layer_id,
        )
        if changed:
            self._refresh_active_scene_content(fit_view=False)
        return changed

    def selectedLayer(self) -> LayerSelectionSnapshot | None:
        """Return selected layer identity in the active scene, if any."""
        selection = self.editorInteraction().selected_layer
        if selection is None:
            return None
        current_scene = self.currentScene()
        return LayerSelectionSnapshot(
            scene_id=(
                selection.scene_id if current_scene is None else current_scene.scene_id
            ),
            layer_id=selection.layer_id,
        )

    def selectedLayers(self) -> tuple[LayerSelectionSnapshot, ...]:
        """Return all selected layers with the active member last."""
        current_scene = self.currentScene()
        if current_scene is None:
            return ()
        return tuple(
            LayerSelectionSnapshot(current_scene.scene_id, selection.layer_id)
            for selection in self.editorInteraction().selected_layers
            if selection.scene_id == current_scene.scene_id
        )

    def setSelectedLayer(self, scene_id: uuid.UUID, layer_id: uuid.UUID) -> bool:
        """Select one policy-enabled layer in the active scene."""
        if not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        if not self._anchor_floating_pixels_before_edit():
            return False
        return self.editorInteraction().select_layer(
            self._resolve_public_scene_id(scene_id),
            layer_id,
        )

    def setSelectedLayers(
        self,
        scene_id: uuid.UUID,
        layer_ids: Sequence[uuid.UUID],
        *,
        active_layer_id: uuid.UUID | None = None,
    ) -> bool:
        """Replace selection with policy-enabled layers in the active scene."""
        if not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        normalized = tuple(layer_ids)
        if not all(isinstance(layer_id, uuid.UUID) for layer_id in normalized):
            raise TypeError("layer_ids must contain only UUID values")
        if active_layer_id is not None and not isinstance(active_layer_id, uuid.UUID):
            raise TypeError("active_layer_id must be a UUID or None")
        if not self._anchor_floating_pixels_before_edit():
            return False
        return self.editorInteraction().select_layers(
            self._resolve_public_scene_id(scene_id),
            normalized,
            active_layer_id=active_layer_id,
        )

    def clearSelectedLayer(self) -> bool:
        """Clear selected-layer identity without changing pixel selection."""
        return bool(
            self._anchor_floating_pixels_before_edit()
            and self.editorInteraction().clear_selected_layer()
        )

    def openComposition(self, composition_id: uuid.UUID) -> None:
        """Open an existing project composition."""
        if not isinstance(composition_id, uuid.UUID):
            raise TypeError("composition_id must be a UUID")
        service = self.compositionService()
        record = service.record(composition_id)
        self._open_composition_record(record)

    def removeComposition(self, composition_id: uuid.UUID) -> None:
        """Remove a policy-enabled composition and open its successor."""
        if not isinstance(composition_id, uuid.UUID):
            raise TypeError("composition_id must be a UUID")
        service = self.compositionService()
        session = self.viewSession()
        previous_id = session.active_composition_id
        if previous_id == composition_id:
            self._cancel_floating_pixels_for_context_change()
        service.remove_composition(composition_id)
        session.reconcile(service.composition_ids())
        active_id = session.active_composition_id
        active = None if active_id is None else service.record(active_id)
        if previous_id == composition_id and active is not None:
            self._open_composition_record(active, force_context_refresh=True)
        elif active is None:
            self.blank()
            self._emit_composition_selection_changed(None)
            self._emit_scene_changed()
        self._emit_composition_changed()
