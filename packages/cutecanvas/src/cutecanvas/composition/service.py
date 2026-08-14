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

"""Composition state owner for CuteCanvas."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import replace

from PySide6.QtCore import QRectF

from qpane.sdk.scene import (
    BilinearLayerTransform,
    LayerInteractionPolicy,
    LayerMapping,
    LayerSourceReference,
    PiecewiseLayerTransform,
)

from ..resources.composition_resources import CompositionResourceOwner
from ..types import (
    CompositionEntry,
    CompositionLayerEntry,
    CompositionSnapshot,
)
from .edit_controller import CompositionEditController
from .edit_history import CompositionEditHistory
from .history_model import HistoryCommit, HistoryTruncation
from .history_policy import CompositionHistoryPolicy
from .layer_edits import (
    CompositionLayerEditService,
    CompositionLayerStackTransition,
    CompositionLayerStackTransitionOwner,
    CompositionLayerTransition,
    CompositionLayerTransitionOwner,
)
from .layers import (
    CompositionLayerInstance,
    CompositionLayerStore,
)
from .model import (
    CompositionDocumentPolicy,
    CompositionOrigin,
    CompositionRecord,
)
from .public_policy import public_document_policy, public_layer_policy
from .resource_lifetime import CompositionResourceLifetime


class CompositionService:
    """Own persistent compositions, layer instances, and chronological edits."""

    def __init__(
        self,
        history_changed: Callable[[uuid.UUID], None] | None = None,
        layers_changed: Callable[[uuid.UUID], None] | None = None,
        source_kind: Callable[[LayerSourceReference], str] | None = None,
        document_resources: CompositionResourceOwner | None = None,
        history_policy: CompositionHistoryPolicy | None = None,
        history_committed: Callable[[HistoryCommit], None] | None = None,
        history_truncated: Callable[[HistoryTruncation], None] | None = None,
    ) -> None:
        """Initialize compositions with optional edit-history observation."""
        self._records: dict[uuid.UUID, CompositionRecord] = {}
        self._order: list[uuid.UUID] = []
        self._revision = 0
        self._layers_changed = layers_changed
        self._document_resources = document_resources
        self._layer_notification_depth = 0
        self._resource_lifetime = CompositionResourceLifetime()
        self._layers = CompositionLayerStore(
            self._resource_lifetime,
            changed=self._handle_layer_store_changed,
            validate_stack=(
                None if document_resources is None else document_resources.validate
            ),
        )
        self._source_kind = source_kind or (lambda source: source.kind)
        self._edit_history = CompositionEditHistory(
            policy=history_policy,
            resource_lifetime=self._resource_lifetime,
            committed=history_committed,
            truncated=history_truncated,
        )
        self._edit_controller = CompositionEditController(
            self._edit_history,
            changed=history_changed,
        )
        self._layer_transitions = CompositionLayerTransitionOwner(self._layers)
        self._edit_controller.register_handler(
            CompositionLayerTransition,
            undo=self._layer_transitions.undo,
            redo=self._layer_transitions.redo,
        )
        self._layer_stack_transitions = CompositionLayerStackTransitionOwner(
            self._layers
        )
        self._edit_controller.register_handler(
            CompositionLayerStackTransition,
            undo=self._layer_stack_transitions.undo,
            redo=self._layer_stack_transitions.redo,
        )
        self._layer_edits = CompositionLayerEditService(
            self._layers,
            self._edit_controller,
            self._resource_lifetime,
        )

    @property
    def layers(self) -> CompositionLayerStore:
        """Return the authoritative composition layer-instance owner."""
        return self._layers

    @property
    def resource_lifetime(self) -> CompositionResourceLifetime:
        """Return the owner of composition source reachability leases."""
        return self._resource_lifetime

    @property
    def edit_history(self) -> CompositionEditHistory:
        """Return authoritative composition editing history."""
        return self._edit_history

    @property
    def edit_controller(self) -> CompositionEditController:
        """Return the dispatcher for chronological composition edits."""
        return self._edit_controller

    @property
    def layer_edits(self) -> CompositionLayerEditService:
        """Return generic undoable layer lifecycle and source edits."""
        return self._layer_edits

    def set_layer_index(
        self,
        composition_id: uuid.UUID,
        layer_id: uuid.UUID,
        index: int,
    ) -> bool:
        """Move one layer to a bottom-to-top stack index as one history edit."""
        layers = list(self._layers.layers_for_composition(composition_id))
        current = next(
            (
                position
                for position, layer in enumerate(layers)
                if layer.layer_id == layer_id
            ),
            -1,
        )
        if current < 0 or not layers or not layers[current].interaction.reorderable:
            return False
        target = max(0, min(int(index), len(layers) - 1))
        if current == target:
            return False
        layer = layers.pop(current)
        layers.insert(target, layer)
        return self._layer_edits.replace_stack(composition_id, tuple(layers))

    def create_composition(
        self,
        bounds: QRectF,
        *,
        title: str,
        origin: CompositionOrigin = CompositionOrigin.COMPOSITION,
        layers: tuple[CompositionLayerInstance, ...] = (),
        policy: CompositionDocumentPolicy | None = None,
        composition_id: uuid.UUID | None = None,
    ) -> CompositionRecord:
        """Create one independent composition."""
        if not isinstance(bounds, QRectF):
            raise TypeError("bounds must be a QRectF")
        if bounds.width() <= 0.0 or bounds.height() <= 0.0:
            raise ValueError("composition bounds must be positive")
        if not isinstance(title, str):
            raise TypeError("title must be a string")
        normalized_title = title.strip()
        if not normalized_title:
            raise ValueError("title must not be empty")
        resolved_composition_id = composition_id or uuid.uuid4()
        if not isinstance(resolved_composition_id, uuid.UUID):
            raise TypeError("composition_id must be a UUID or None")
        if resolved_composition_id in self._records:
            raise ValueError("composition_id already exists")
        record = CompositionRecord(
            composition_id=resolved_composition_id,
            origin=origin,
            title=normalized_title,
            canvas_bounds=QRectF(bounds),
            policy=policy or CompositionDocumentPolicy(),
        )
        self._records[resolved_composition_id] = record
        self._layer_notification_depth += 1
        try:
            self._layers.ensure_composition(resolved_composition_id, tuple(layers))
        finally:
            self._layer_notification_depth -= 1
        self._order.append(resolved_composition_id)
        if self._document_resources is not None:
            try:
                self._document_resources.synchronize(resolved_composition_id, layers)
            except Exception:
                self._records.pop(resolved_composition_id, None)
                self._layers.remove_composition(resolved_composition_id)
                self._order.remove(resolved_composition_id)
                raise
        self._touch()
        return record

    def fork_composition(self, composition_id: uuid.UUID) -> uuid.UUID | None:
        """Clone one composition while sharing each referenced child resource."""
        source = self._records.get(composition_id)
        if source is None:
            return None
        layers = tuple(
            replace(layer, layer_id=uuid.uuid4())
            for layer in self._layers.layers_for_composition(composition_id)
        )
        forked = self.create_composition(
            source.canvas_bounds,
            title=f"{source.title} copy",
            origin=source.origin,
            layers=layers,
            policy=source.policy,
        )
        return forked.composition_id

    def set_document_policy(
        self,
        composition_id: uuid.UUID,
        policy: CompositionDocumentPolicy,
    ) -> bool:
        """Replace host-controlled composition policy without changing its origin."""
        record = self.record(composition_id)
        replacement = replace(record, policy=policy)
        if replacement == record:
            return False
        self._records[composition_id] = replacement
        self._touch()
        return True

    def set_canvas_bounds(
        self,
        composition_id: uuid.UUID,
        bounds: QRectF,
    ) -> bool:
        """Replace intrinsic composition bounds without changing its identity."""
        if not isinstance(bounds, QRectF):
            raise TypeError("bounds must be a QRectF")
        if bounds.width() <= 0.0 or bounds.height() <= 0.0:
            raise ValueError("composition bounds must be positive")
        record = self.record(composition_id)
        replacement = replace(record, canvas_bounds=QRectF(bounds))
        if replacement == record:
            return False
        self._records[composition_id] = replacement
        self._touch()
        if self._layers_changed is not None:
            self._layers_changed(composition_id)
        return True

    def remove_layer(self, composition_id: uuid.UUID, layer_id: uuid.UUID) -> bool:
        """Remove one host-policy-enabled layer as one history command."""
        return self._layer_edits.remove(composition_id, layer_id)

    def restore_document(
        self,
        document: CompositionRecord,
        layers: tuple[CompositionLayerInstance, ...],
    ) -> None:
        """Transactionally replace one complete persisted composition document."""
        composition_id = document.composition_id
        existed = composition_id in self._records
        previous_record = self._records.get(composition_id)
        previous_layers = self._layers.layers_for_composition(composition_id)
        previous_order = tuple(self._order)
        try:
            self._records[composition_id] = document
            if existed:
                self._layers.replace_layers(composition_id, tuple(layers))
            else:
                self._layers.ensure_composition(composition_id, tuple(layers))
                self._order.append(composition_id)
            if self._document_resources is not None:
                self._document_resources.synchronize(composition_id, layers)
            self._touch()
        except Exception:
            if previous_record is None:
                self._records.pop(composition_id, None)
                self._layers.remove_composition(composition_id)
            else:
                self._records[composition_id] = previous_record
                self._layers.replace_layers(composition_id, previous_layers)
            self._order = list(previous_order)
            raise

    def restore_documents(
        self,
        documents: dict[uuid.UUID, CompositionRecord],
        layer_stacks: dict[uuid.UUID, tuple[CompositionLayerInstance, ...]],
    ) -> None:
        """Transactionally merge a complete nested composition set."""
        if set(documents) != set(layer_stacks):
            raise ValueError("documents and layer stacks must have identical keys")
        previous_records = {
            document_id: self._records.get(document_id) for document_id in documents
        }
        previous_layers = {
            document_id: self._layers.layers_for_composition(document_id)
            for document_id in documents
        }
        previous_order = tuple(self._order)
        self._layer_notification_depth += 1
        try:
            for document_id in sorted(documents, key=str):
                document = documents[document_id]
                if document.composition_id != document_id:
                    raise ValueError("document key must match its composition identity")
                self._records[document_id] = document
                if document_id in self._order:
                    self._layers.replace_layers(
                        document_id,
                        layer_stacks[document_id],
                    )
                else:
                    self._layers.ensure_composition(
                        document_id,
                        layer_stacks[document_id],
                    )
                    self._order.append(document_id)
                if self._document_resources is not None:
                    self._document_resources.synchronize(
                        document_id,
                        layer_stacks[document_id],
                    )
            self._touch()
        except Exception:
            for document_id, previous in previous_records.items():
                if previous is None:
                    self._records.pop(document_id, None)
                    self._layers.remove_composition(document_id)
                else:
                    self._records[document_id] = previous
                    self._layers.replace_layers(
                        document_id,
                        previous_layers[document_id],
                    )
            self._order = list(previous_order)
            raise
        finally:
            self._layer_notification_depth -= 1

    def clear(self) -> bool:
        """Remove every composition."""
        if not self._records:
            return False
        if self._document_resources is not None:
            self._document_resources.remove_many(self._records)
        self._records.clear()
        self._order.clear()
        self._layers.clear()
        self._edit_history.clear()
        self._touch()
        return True

    def update_scene_layer_interaction(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        interaction: LayerInteractionPolicy,
    ) -> bool:
        """Replace interaction permissions for one stored scene layer."""
        record = self._records.get(scene_id)
        if record is None:
            return False
        changed = self._layers.update_interaction(scene_id, layer_id, interaction)
        if changed:
            self._touch()
        return changed

    def update_scene_layer_transform(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        transform: LayerMapping,
    ) -> bool:
        """Replace exact geometry for one stored composition layer."""
        record = self._records.get(scene_id)
        if record is None or self._layers.layer(scene_id, layer_id) is None:
            return False
        changed = self._layers.update_mapping(scene_id, layer_id, transform)
        if changed:
            self._touch()
        return changed

    def remove_composition(self, composition_id: uuid.UUID) -> bool:
        """Remove an explicit or layered composition."""
        record = self.record(composition_id)
        if not record.policy.removable:
            raise ValueError("composition policy prevents removal")
        if self._document_resources is not None:
            self._document_resources.remove(composition_id)
        self._records.pop(composition_id, None)
        self._layers.remove_composition(composition_id)
        self._edit_history.clear_scope(composition_id)
        self._order = [item for item in self._order if item != composition_id]
        self._touch()
        return True

    def record(self, composition_id: uuid.UUID) -> CompositionRecord:
        """Return a composition record or raise for unknown IDs."""
        if not isinstance(composition_id, uuid.UUID):
            raise TypeError("composition_id must be a UUID")
        record = self._records.get(composition_id)
        if record is None:
            raise KeyError("composition_id does not exist")
        return record

    def composition_ids(self) -> tuple[uuid.UUID, ...]:
        """Return composition IDs in browser order."""
        return tuple(self._order)

    def snapshot(
        self,
        *,
        active_composition_id: uuid.UUID | None = None,
    ) -> CompositionSnapshot:
        """Return a public immutable snapshot of all compositions."""
        compositions: dict[uuid.UUID, CompositionEntry] = {}
        for composition_id in self._order:
            record = self._records.get(composition_id)
            if record is None:
                continue
            compositions[composition_id] = self._entry(record)
        return CompositionSnapshot(
            compositions=compositions,
            order=tuple(compositions),
            current_composition_id=active_composition_id,
        )

    def revision(self) -> int:
        """Return a revision for render-relevant composition state."""
        return self._revision

    def _entry(self, record: CompositionRecord) -> CompositionEntry:
        """Convert an internal record into a public snapshot entry."""
        instances = self._layers.layers_for_composition(record.composition_id)
        return CompositionEntry(
            composition_id=record.composition_id,
            kind=record.origin.value,
            title=record.title,
            scene_layer_count=len(instances),
            scene_bounds=QRectF(record.canvas_bounds),
            layers=tuple(self._layer_entry(instance) for instance in instances),
            policy=public_document_policy(record.policy),
        )

    def source_kind(self, source: LayerSourceReference) -> str:
        """Return the authoritative semantic kind for one stable layer source."""
        return self._source_kind(source)

    def _layer_entry(
        self,
        instance: CompositionLayerInstance,
    ) -> CompositionLayerEntry:
        """Detach one ordered layer instance for composition browser clients."""
        return CompositionLayerEntry(
            layer_id=instance.layer_id,
            source_kind=self.source_kind(instance.source),
            source_id=instance.source.resource_id,
            label=instance.label,
            role=instance.role,
            visible=instance.visible,
            opacity=instance.opacity,
            interaction=public_layer_policy(instance.interaction),
            transform=(
                instance.transform
                if isinstance(
                    instance.transform,
                    (PiecewiseLayerTransform, BilinearLayerTransform),
                )
                else instance.transform.to_qtransform()
            ),
        )

    def _touch(self) -> None:
        """Advance the composition revision."""
        self._revision += 1

    def _handle_layer_store_changed(self, composition_id: uuid.UUID) -> None:
        """Publish only stack mutations belonging to a complete stored record."""
        if (
            self._document_resources is not None
            and composition_id in self._records
            and composition_id in self._order
        ):
            self._document_resources.synchronize(
                composition_id,
                self._layers.layers_for_composition(composition_id),
            )
        if (
            self._layers_changed is not None
            and self._layer_notification_depth == 0
            and composition_id in self._records
            and composition_id in self._order
        ):
            self._layers_changed(composition_id)
