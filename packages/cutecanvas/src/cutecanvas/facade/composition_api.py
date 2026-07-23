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
from dataclasses import replace

from PySide6.QtCore import (
    QPoint,
    QRectF,
)
from PySide6.QtGui import (
    QTransform,
)
from qpane.sdk.scene import LayerPlacement, LayerTransform

from cutecanvas.composition.geometry_policy import LayerGeometryPolicy
from cutecanvas.composition.public_policy import (
    internal_document_policy,
    internal_layer_policy,
)
from cutecanvas.types import (
    CompositionPolicy,
    CompositionRequest,
    CompositionTemplate,
    LayerHit,
    LayerPolicy,
    LayerSelectionSnapshot,
    SceneSnapshot,
    TemplateBindings,
)


class CompositionApiMixin:
    """Group compositionapi facade behavior."""

    def composeScene(
        self,
        request: CompositionRequest,
        *,
        activate: bool = True,
        fit_view: bool = True,
    ) -> uuid.UUID:
        """Create or replace a stored catalog-backed scene composition.

        Args:
            request: Scene composition request whose layers reference catalog image IDs.
            activate: Open the stored composition immediately when True.
            fit_view: Fit the composed scene bounds when activation occurs.

        Raises:
            TypeError: If request objects have invalid types.
            ValueError: If scene geometry, layer values, or replacement targets are invalid.
            KeyError: If a layer references an image ID outside the catalog.

        Side effects:
            Stores a composition record, optionally opens it, and emits
            composition and scene signals.
        """
        previous_active_id = self.currentCompositionID()
        record = self.compositionService().compose_scene(
            request,
            catalog_contains=self._image_catalog.containsImage,
            activate=activate,
        )
        self._emit_composition_changed()
        if activate:
            self._open_composition_record(record, fit_view=fit_view)
        elif record.composition_id == previous_active_id:
            self._refresh_active_scene_content(fit_view=fit_view)
        return record.composition_id

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
        image_id: uuid.UUID,
        *,
        title: str | None = None,
        interaction: LayerPolicy | None = None,
        policy: CompositionPolicy | None = None,
        fit_view: bool = True,
    ) -> uuid.UUID:
        """Create an independent composition seeded by a catalog resource.

        Args:
            image_id: Existing catalog resource used for canvas size and first layer.
            title: Optional document title derived from the catalog path when omitted.
            interaction: Host policy for the ordinary seeded layer.
            policy: Optional document-level removal and comparison permissions.
            fit_view: Fit the new canvas in the viewport when True.

        Returns:
            The independent composition UUID.

        Side effects:
            Opens the document and emits composition and scene signals.
        """
        if not isinstance(image_id, uuid.UUID):
            raise TypeError("image_id must be a UUID")
        if not self._image_catalog.containsImage(image_id):
            raise KeyError("image_id must exist in the catalog")
        if title is not None and not isinstance(title, str):
            raise TypeError("title must be a string or None")
        if interaction is not None and not isinstance(
            interaction,
            LayerPolicy,
        ):
            raise TypeError("interaction must be LayerPolicy or None")
        if policy is not None and not isinstance(policy, CompositionPolicy):
            raise TypeError("policy must be CompositionPolicy or None")
        path = self.imagePath(image_id)
        resolved_title = title or (path.name if path is not None else "Composition")
        record = self.compositionService().create_from_catalog_image(
            image_id,
            title=resolved_title,
            interaction=internal_layer_policy(interaction or LayerPolicy()),
            policy=internal_document_policy(policy or CompositionPolicy()),
        )
        self._emit_composition_changed()
        self._open_composition_record(record, fit_view=fit_view)
        return record.composition_id

    def addCatalogImageLayer(
        self,
        image_id: uuid.UUID,
        *,
        placement: QRectF | None = None,
        label: str | None = None,
        interaction: LayerPolicy | None = None,
    ) -> uuid.UUID | None:
        """Place one shared catalog resource in the active composition.

        Args:
            image_id: Existing catalog resource to place.
            placement: Optional scene-space destination rectangle.
            label: Optional composition-local display label.
            interaction: Host policy for the new independent instance.

        Returns:
            The new layer UUID, or None when no composition is active.

        Side effects:
            Adds one undoable layer instance and refreshes the active scene.
        """
        if not isinstance(image_id, uuid.UUID):
            raise TypeError("image_id must be a UUID")
        if not self._image_catalog.containsImage(image_id):
            raise KeyError("image_id must exist in the catalog")
        if placement is not None and not isinstance(placement, QRectF):
            raise TypeError("placement must be a QRectF or None")
        if label is not None and not isinstance(label, str):
            raise TypeError("label must be a string or None")
        if interaction is not None and not isinstance(
            interaction,
            LayerPolicy,
        ):
            raise TypeError("interaction must be LayerPolicy or None")
        layer_id = self.compositionService().add_catalog_layer(
            image_id,
            placement=self._layer_placement(placement),
            interaction=internal_layer_policy(interaction or LayerPolicy()),
            label=label,
        )
        if layer_id is not None:
            self._refresh_active_scene_content(fit_view=False)
        return layer_id

    def setCompositionPolicy(
        self,
        composition_id: uuid.UUID,
        policy: CompositionPolicy,
    ) -> bool:
        """Replace structural permissions for one composition document.

        Args:
            composition_id: Existing composition identity.
            policy: Host-selected removal and comparison permissions.

        Returns:
            True when document policy or comparison state changed.

        Side effects:
            Clears an existing comparison when comparison becomes disabled and
            emits composition state when a change occurs.
        """
        if not isinstance(composition_id, uuid.UUID):
            raise TypeError("composition_id must be a UUID")
        if not isinstance(policy, CompositionPolicy):
            raise TypeError("policy must be CompositionPolicy")
        record = self.compositionService().record(composition_id)
        changed = self.compositionService().set_document_policy(
            composition_id,
            internal_document_policy(
                policy,
                remove_if_catalog_resource_missing=(
                    record.policy.remove_if_catalog_resource_missing
                ),
            ),
        )
        if changed:
            self._emit_composition_changed()
            if self.currentCompositionID() == composition_id:
                self._handle_comparison_changed()
        return changed

    def composeSceneFromTemplate(
        self,
        template: CompositionTemplate,
        bindings: TemplateBindings,
        *,
        activate: bool = True,
        fit_view: bool = True,
    ) -> uuid.UUID:
        """Create or replace a stored scene composition from a host template.

        Args:
            template: Host-owned reusable template object.
            bindings: Catalog image bindings for this composition instance.
            activate: Open the stored composition immediately when True.
            fit_view: Fit the composed scene bounds when activation occurs.

        Side effects:
            Stores a composition record, optionally opens it, and emits
            composition and scene signals.
        """
        previous_active_id = self.currentCompositionID()
        record = self.compositionService().compose_scene_from_template(
            template,
            bindings,
            catalog_contains=self._image_catalog.containsImage,
            activate=activate,
        )
        self._emit_composition_changed()
        if activate:
            self._open_composition_record(record, fit_view=fit_view)
        elif record.composition_id == previous_active_id:
            self._refresh_active_scene_content(fit_view=fit_view)
        return record.composition_id

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
    ) -> QTransform | None:
        """Return one active layer's detached exact local-to-scene transform.

        Args:
            scene_id: Public or resolved identifier for the active scene.
            layer_id: Stable identifier of the layer to inspect.

        Returns:
            A detached affine transform, or None when the layer is unavailable.

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
        return None if instance is None else instance.transform.to_qtransform()

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
        transform: QTransform,
    ) -> bool:
        """Set one movable active layer's exact affine local-to-scene transform.

        Args:
            scene_id: Public or resolved identifier for the active scene.
            layer_id: Stable identifier of the layer to transform.
            transform: Finite, invertible affine local-to-scene mapping.

        Returns:
            True when geometry changed and one history command was recorded.

        Raises:
            TypeError: If identifiers or transform use unsupported types.
            ValueError: If the transform is projective, singular, or non-finite.

        Side effects:
            Refreshes scene rendering and emits scene/history signals after a change.
        """
        if not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        if not isinstance(transform, QTransform):
            raise TypeError("transform must be a QTransform")
        normalized = LayerTransform.from_qtransform(QTransform(transform))
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

    def clearSelectedLayer(self) -> bool:
        """Clear selected-layer identity without changing pixel selection."""
        return bool(
            self._anchor_floating_pixels_before_edit()
            and self.editorInteraction().clear_selected_layer()
        )
