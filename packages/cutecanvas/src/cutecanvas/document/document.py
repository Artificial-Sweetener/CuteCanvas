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
"""Headless host-owned CuteCanvas document aggregate."""

from __future__ import annotations

import uuid
from math import ceil

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage

from ..composition.public_policy import (
    internal_document_policy,
    internal_layer_policy,
)
from ..editor.floating_history import FloatingPixelHistory
from ..editor.floating_layers import FloatingLayerPromotionRegistry
from ..masks.floating_layers import MaskFloatingLayerOwner
from ..masks.mask import MaskAssetStore
from ..raster.floating_layers import EditableRasterFloatingLayerOwner
from ..resources.document_core import DocumentResourceCore
from ..resources.model import ProjectResourceReference
from ..resources.pixel_history import (
    ResourcePixelHistoryOwner,
    ResourcePixelTransitionOwner,
)
from ..scene.pixel_edits import RasterPixelEdit
from ..types import (
    CompositionPolicy,
    CompositionSnapshot,
    LayerPolicy,
)
from ..vector.document_core import VectorDocumentCore
from .events import DocumentChange, DocumentChangeKind, DocumentEventHub
from .references import (
    CanvasContentKind,
    CanvasContentReference,
    ResolvedCanvasContent,
)


class CanvasDocument:
    """Own editable content and history independently of any QWidget."""

    def __init__(self) -> None:
        """Construct durable editable state without process-runtime ownership."""
        self._document_id = uuid.uuid4()
        self._events = DocumentEventHub()
        self._content_revisions: dict[uuid.UUID, int] = {}
        self._content_revision_unsubscribe = self._events.subscribe(
            self._advance_content_revision
        )
        self._resources = DocumentResourceCore.create(
            history_changed=self._events.history_changed,
            layers_changed=self._events.layers_changed,
            pixel_selection_changed=self._events.selection_changed,
            resource_changed=self._events.resource_changed,
        )
        self._vectors = VectorDocumentCore.create(
            compositions=self._resources.compositions,
            resources=self._resources.resources,
            lifecycle=self._resources.lifecycle,
            changed=self._events.resource_changed,
        )
        self._masks = MaskAssetStore(
            self._resources.resources,
            changed=self._events.resource_changed,
        )
        self._masks.bind_composition_edits(
            self._resources.compositions.edit_controller,
            self._composition_scope_for_mask,
        )
        pixel_history = ResourcePixelHistoryOwner(
            resources=self._resources.resources,
            rasters=self._resources.editable_raster_assets,
            masks=self._masks,
            changed=self._events.resource_changed,
        )
        self._resources.compositions.edit_controller.register_handler(
            RasterPixelEdit,
            undo=pixel_history.undo,
            redo=pixel_history.redo,
        )
        transition_history = ResourcePixelTransitionOwner(
            resources=self._resources.resources,
            layers=self._resources.compositions.layers,
            rasters=self._resources.editable_raster_assets,
            masks=self._masks,
            changed=self._events.resource_changed,
        )
        history_promotions = FloatingLayerPromotionRegistry()
        history_promotions.register(
            EditableRasterFloatingLayerOwner(
                assets=self._resources.editable_raster_assets,
                layers=self._resources.compositions.layers,
                current_composition_id=lambda: None,
                changed=lambda: None,
            )
        )
        history_promotions.register(
            MaskFloatingLayerOwner(
                assets=self._masks,
                layers=self._resources.compositions.layers,
                current_composition_id=lambda: None,
                changed=lambda _mask_id: None,
            )
        )
        self._floating_history = FloatingPixelHistory(
            edits=self._resources.compositions.edit_controller,
            transitions=transition_history,
            pixel_selection=self._resources.pixel_selection,
            promotions=history_promotions,
        )
        self._closed = False

    @property
    def document_id(self) -> uuid.UUID:
        """Return this headless document's stable runtime identity."""
        return self._document_id

    @property
    def events(self) -> DocumentEventHub:
        """Return the document change subscription owner."""
        return self._events

    @property
    def resources(self) -> DocumentResourceCore:
        """Return durable resource-domain owners for view adapters."""
        return self._resources

    @property
    def vectors(self) -> VectorDocumentCore:
        """Return durable semantic vector owners."""
        return self._vectors

    @property
    def masks(self) -> MaskAssetStore:
        """Return durable hybrid mask assets."""
        return self._masks

    @property
    def floating_history(self) -> FloatingPixelHistory:
        """Return document-owned atomic floating-pixel history replay."""
        return self._floating_history

    def composition_ids(self) -> tuple[uuid.UUID, ...]:
        """Return composition identities in stable document order."""
        return self._resources.compositions.composition_ids()

    def snapshot(self) -> CompositionSnapshot:
        """Return detached document content without view activation state."""
        return self._resources.compositions.snapshot()

    def create_composition(
        self,
        bounds: QRectF,
        *,
        title: str = "Untitled",
        policy: CompositionPolicy | None = None,
    ) -> uuid.UUID:
        """Create and return one independent composition identity."""
        record = self._resources.compositions.create_composition(
            bounds,
            title=title,
            policy=internal_document_policy(policy or CompositionPolicy()),
        )
        self._events.layers_changed(record.composition_id)
        return record.composition_id

    def create_composition_from_image(
        self,
        image: QImage,
        *,
        title: str = "Untitled",
        label: str | None = None,
        interaction: LayerPolicy | None = None,
        policy: CompositionPolicy | None = None,
        composition_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        """Import detached pixels and return one seeded composition identity."""
        result = self._resources.image_documents.create(
            image,
            title=title,
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
            document_id=composition_id,
        )
        self._events.layers_changed(result.document_id)
        return result.document_id

    def replace_composition_image(
        self,
        composition_id: uuid.UUID,
        image: QImage,
    ) -> bool:
        """Replace one imported composition's pixels without changing view state."""
        result = self._resources.image_documents.replace(composition_id, image)
        self._events.resource_changed(result.resource_id)
        return True

    def embedded_image_for_composition(self, composition_id: uuid.UUID) -> QImage:
        """Return detached pixels for a single-image composition.

        Native catalog presentations consume the imported Output image directly;
        they must not reconstruct a second document renderer or silently flatten
        a layered editable composition.  Callers therefore receive a clear
        error when the requested composition is not the direct imported-image
        form created by :meth:`create_composition_from_image`.
        """
        self._resources.compositions.record(composition_id)
        layers = self._resources.compositions.layers.layers_for_composition(
            composition_id
        )
        if not layers:
            bounds = self._resources.compositions.record(composition_id).canvas_bounds
            image = QImage(
                max(1, ceil(bounds.width())),
                max(1, ceil(bounds.height())),
                QImage.Format.Format_ARGB32_Premultiplied,
            )
            image.fill(0)
            return image
        content_layers = tuple(layer for layer in layers if layer.role == "content")
        if len(content_layers) != 1:
            raise ValueError(
                "composition does not have one embedded content image layer"
            )
        source = content_layers[0].source
        if not isinstance(source, ProjectResourceReference):
            raise TypeError("composition layer does not reference a project resource")
        snapshot = self._resources.placed_assets.get(source.resource_id)
        if snapshot is None or snapshot.image is None or snapshot.image.isNull():
            raise ValueError("composition does not retain embedded image pixels")
        return QImage(snapshot.image)

    def remove_composition(self, composition_id: uuid.UUID) -> bool:
        """Remove one policy-enabled composition and publish its disappearance."""
        changed = self._resources.compositions.remove_composition(composition_id)
        if changed:
            self._events.layers_changed(composition_id)
        return changed

    def content_reference(
        self,
        composition_id: uuid.UUID,
        *,
        layer_id: uuid.UUID | None = None,
    ) -> CanvasContentReference:
        """Return a stable reference to a composition or one layer instance."""
        self._resources.compositions.record(composition_id)
        if layer_id is None:
            return CanvasContentReference(
                self._document_id,
                CanvasContentKind.COMPOSITION,
                composition_id=composition_id,
                instance_revision=self._content_revisions.get(composition_id, 0),
            )
        layer = self._resources.compositions.layers.layer(
            composition_id,
            layer_id,
        )
        if layer is None:
            raise KeyError("layer_id does not exist in the composition")
        resource = self._resources.resources.get(layer.source.resource_id)
        if resource is None:
            raise KeyError("layer resource no longer exists")
        return CanvasContentReference(
            self._document_id,
            CanvasContentKind.LAYER,
            composition_id=composition_id,
            layer_id=layer_id,
            resource_id=resource.resource_id,
            instance_revision=self._resources.compositions.layers.instance_revision(
                composition_id,
                layer_id,
            ),
            resource_revision=resource.revision,
        )

    def resource_reference(
        self,
        resource_id: uuid.UUID,
    ) -> CanvasContentReference:
        """Return a stable reference to one retained reusable resource."""
        resource = self._resources.resources.get(resource_id)
        if resource is None:
            raise KeyError("resource_id does not exist")
        return CanvasContentReference(
            self._document_id,
            CanvasContentKind.RESOURCE,
            resource_id=resource_id,
            resource_revision=resource.revision,
        )

    def resolve_content(
        self,
        reference: CanvasContentReference,
    ) -> ResolvedCanvasContent:
        """Resolve a reference and report whether its observed revision is stale."""
        if reference.document_id != self._document_id:
            raise ValueError("content reference belongs to another document")
        if reference.kind is CanvasContentKind.COMPOSITION:
            assert reference.composition_id is not None
            current = self.content_reference(reference.composition_id)
        elif reference.kind is CanvasContentKind.LAYER:
            assert reference.composition_id is not None
            assert reference.layer_id is not None
            current = self.content_reference(
                reference.composition_id,
                layer_id=reference.layer_id,
            )
        else:
            assert reference.resource_id is not None
            current = self.resource_reference(reference.resource_id)
        return ResolvedCanvasContent(reference, current)

    def close(self) -> None:
        """Release durable document subscriptions and event observers."""
        if self._closed:
            return
        self._closed = True
        self._content_revision_unsubscribe()
        self._events.clear()

    def _composition_scope_for_mask(
        self,
        mask_id: uuid.UUID,
    ) -> uuid.UUID | None:
        """Resolve one mask resource to its first composition owner."""
        compositions = self._resources.compositions
        for composition_id in compositions.composition_ids():
            if any(
                layer.source.resource_id == mask_id
                for layer in compositions.layers.layers_for_composition(composition_id)
            ):
                return composition_id
        return None

    def _advance_content_revision(self, change: DocumentChange) -> None:
        """Advance only compositions whose projected pixels may have changed."""
        composition_ids: set[uuid.UUID] = set()
        if change.composition_id is not None:
            composition_ids.add(change.composition_id)
        if (
            change.kind is DocumentChangeKind.RESOURCE
            and change.resource_id is not None
        ):
            layers = self._resources.compositions.layers
            for composition_id in self._resources.compositions.composition_ids():
                if any(
                    layer.source.resource_id == change.resource_id
                    for layer in layers.layers_for_composition(composition_id)
                ):
                    composition_ids.add(composition_id)
        for composition_id in composition_ids:
            self._content_revisions[composition_id] = (
                self._content_revisions.get(composition_id, 0) + 1
            )
