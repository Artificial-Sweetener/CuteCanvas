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
from collections.abc import Callable, Iterable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QRectF, QSize
from qpane.sdk.catalog import CatalogImageReference
from qpane.sdk.scene import (
    LayerInteractionPolicy,
    LayerPlacement,
    LayerSourceReference,
    LayerTransform,
    RasterBounds,
)
from qpane.sdk.types import (
    ComparisonOrientation,
    ComparisonState,
)

from ..types import (
    CompositionEntry,
    CompositionLayerEntry,
    CompositionRequest,
    CompositionSnapshot,
    CompositionTemplate,
    TemplateBindings,
)
from .edit_controller import CompositionEditController
from .edit_history import CompositionEditHistory
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
    CompositionComparison,
    CompositionDocumentPolicy,
    CompositionOrigin,
    CompositionRecord,
)
from .public_policy import public_document_policy, public_layer_policy
from .request_composer import CompositionRequestComposer
from .resource_lifetime import CompositionResourceLifetime


class CompositionService:
    """Own persistent compositions and active-composition state."""

    def __init__(
        self,
        history_changed: Callable[[uuid.UUID], None] | None = None,
        layers_changed: Callable[[uuid.UUID], None] | None = None,
        catalog_size: Callable[[uuid.UUID], QSize] | None = None,
        catalog_reference: Callable[[uuid.UUID], LayerSourceReference] | None = None,
    ) -> None:
        """Initialize compositions with optional edit-history observation."""
        self._records: dict[uuid.UUID, CompositionRecord] = {}
        self._order: list[uuid.UUID] = []
        self._default_by_image_id: dict[uuid.UUID, uuid.UUID] = {}
        self._active_id: uuid.UUID | None = None
        self._default_split_position = 0.5
        self._default_orientation = ComparisonOrientation.VERTICAL
        self._revision = 0
        self._layers_changed = layers_changed
        self._layer_notification_depth = 0
        self._resource_lifetime = CompositionResourceLifetime()
        self._layers = CompositionLayerStore(
            self._resource_lifetime,
            changed=self._handle_layer_store_changed,
        )
        self._catalog_size = catalog_size
        self._catalog_reference = catalog_reference
        self._request_composer = CompositionRequestComposer(
            catalog_bounds=self._catalog_bounds,
            catalog_source=self._catalog_source,
        )
        self._edit_history = CompositionEditHistory(
            resource_lifetime=self._resource_lifetime
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
        navigation_image_id: uuid.UUID | None = None,
        layers: tuple[CompositionLayerInstance, ...] = (),
        policy: CompositionDocumentPolicy | None = None,
    ) -> CompositionRecord:
        """Create and activate one independent composition document."""
        if not isinstance(bounds, QRectF):
            raise TypeError("bounds must be a QRectF")
        if bounds.width() <= 0.0 or bounds.height() <= 0.0:
            raise ValueError("composition bounds must be positive")
        if not isinstance(title, str):
            raise TypeError("title must be a string")
        normalized_title = title.strip()
        if not normalized_title:
            raise ValueError("title must not be empty")
        composition_id = uuid.uuid4()
        record = CompositionRecord(
            composition_id=composition_id,
            origin=origin,
            title=normalized_title,
            canvas_bounds=QRectF(bounds),
            navigation_image_id=navigation_image_id,
            policy=policy or CompositionDocumentPolicy(),
        )
        self._records[composition_id] = record
        self._layer_notification_depth += 1
        try:
            self._layers.ensure_composition(composition_id, tuple(layers))
        finally:
            self._layer_notification_depth -= 1
        self._order.append(composition_id)
        self._active_id = composition_id
        self._touch()
        return record

    def create_from_catalog_image(
        self,
        image_id: uuid.UUID,
        *,
        title: str,
        interaction: LayerInteractionPolicy,
        policy: CompositionDocumentPolicy | None = None,
    ) -> CompositionRecord:
        """Create an independent document seeded by one ordinary catalog layer."""
        bounds = self._catalog_bounds(image_id)
        instance = CompositionLayerInstance(
            layer_id=uuid.uuid4(),
            source=self._catalog_source(image_id),
            transform=LayerTransform(),
            interaction=interaction,
            role="content",
        )
        return self.create_composition(
            QRectF(0.0, 0.0, bounds.width, bounds.height),
            title=title,
            navigation_image_id=image_id,
            layers=(instance,),
            policy=policy or CompositionDocumentPolicy(),
        )

    def set_document_policy(
        self,
        composition_id: uuid.UUID,
        policy: CompositionDocumentPolicy,
    ) -> bool:
        """Replace host-controlled document policy without changing its origin."""
        record = self.record(composition_id)
        comparison = record.comparison if policy.comparison_enabled else None
        replacement = replace(record, policy=policy, comparison=comparison)
        if replacement == record:
            return False
        self._records[composition_id] = replacement
        self._touch()
        return True

    def add_catalog_layer(
        self,
        image_id: uuid.UUID,
        *,
        placement: LayerPlacement | None,
        interaction: LayerInteractionPolicy,
        label: str | None,
    ) -> uuid.UUID | None:
        """Place one shared catalog resource in the active composition."""
        composition_id = self._active_id
        if composition_id is None:
            return None
        bounds = self._catalog_bounds(image_id)
        transform = (
            LayerTransform()
            if placement is None
            else LayerTransform.from_placement(bounds, placement)
        )
        layer_id = uuid.uuid4()
        instance = CompositionLayerInstance(
            layer_id=layer_id,
            source=self._catalog_source(image_id),
            transform=transform,
            interaction=interaction,
            label=label.strip() if label is not None and label.strip() else None,
            role="content",
        )
        return layer_id if self._layer_edits.add(composition_id, instance) else None

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
        previous_active = self._active_id
        try:
            self._records[composition_id] = document
            if existed:
                self._layers.replace_layers(composition_id, tuple(layers))
            else:
                self._layers.ensure_composition(composition_id, tuple(layers))
                self._order.append(composition_id)
            self._active_id = composition_id
            self._touch()
        except Exception:
            if previous_record is None:
                self._records.pop(composition_id, None)
                self._layers.remove_composition(composition_id)
            else:
                self._records[composition_id] = previous_record
                self._layers.replace_layers(composition_id, previous_layers)
            self._order = list(previous_order)
            self._active_id = previous_active
            raise

    def sync_catalog(
        self,
        image_ids: Iterable[uuid.UUID],
        *,
        path_lookup: Callable[[uuid.UUID], Path | None],
        size_lookup: Callable[[uuid.UUID], QSize],
    ) -> bool:
        """Synchronize generated default compositions with catalog images."""
        ordered_ids = tuple(image_ids)
        valid_ids = set(ordered_ids)
        changed = self._remove_invalid_catalog_references(valid_ids, touch=False)
        for index, image_id in enumerate(ordered_ids):
            if image_id in self._default_by_image_id:
                continue
            image_size = size_lookup(image_id)
            composition_id = uuid.uuid4()
            placement = LayerPlacement(
                0.0,
                0.0,
                float(image_size.width()),
                float(image_size.height()),
            )
            bounds = RasterBounds.from_size(image_size)
            self._layers.ensure_composition(
                composition_id,
                (
                    CompositionLayerInstance(
                        layer_id=uuid.uuid4(),
                        source=self._catalog_source(image_id),
                        transform=LayerTransform.from_placement(bounds, placement),
                        interaction=LayerInteractionPolicy(
                            reorderable=False,
                            removable=False,
                        ),
                        role="base-image",
                    ),
                ),
            )
            title = self._default_title(path_lookup(image_id), index)
            record = CompositionRecord(
                composition_id=composition_id,
                origin=CompositionOrigin.DEFAULT_IMAGE,
                title=title,
                canvas_bounds=QRectF(
                    0.0,
                    0.0,
                    float(image_size.width()),
                    float(image_size.height()),
                ),
                navigation_image_id=image_id,
                policy=CompositionDocumentPolicy(removable=False),
            )
            self._records[composition_id] = record
            self._default_by_image_id[image_id] = composition_id
            self._order.append(composition_id)
            changed = True
        if self._active_id is not None and self._active_id not in self._records:
            self._active_id = None
            changed = True
        if changed:
            self._touch()
        return changed

    def clear(self) -> bool:
        """Remove every composition."""
        if not self._records and self._active_id is None:
            return False
        self._records.clear()
        self._order.clear()
        self._default_by_image_id.clear()
        self._layers.clear()
        self._edit_history.clear()
        self._active_id = None
        self._touch()
        return True

    def clear_selection(self) -> bool:
        """Clear the active composition without removing records."""
        if self._active_id is None:
            return False
        self._active_id = None
        self._touch()
        return True

    def compose(
        self,
        image_ids: Iterable[uuid.UUID],
        *,
        title: str | None,
        path_lookup: Callable[[uuid.UUID], Path | None],
    ) -> CompositionRecord:
        """Create and activate a legacy image-seeded composition adapter."""
        source_ids = tuple(image_ids)
        if not 1 <= len(source_ids) <= 2:
            raise ValueError("compose currently accepts one or two catalog image IDs")
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("compose image IDs must be unique")
        composition_id = uuid.uuid4()
        comparison = None
        if len(source_ids) == 2:
            comparison_id = source_ids[1]
            comparison = CompositionComparison(
                source_id=comparison_id,
                source_path=path_lookup(comparison_id),
                source_kind="catalog",
                split_position=self._default_split_position,
                orientation=self._default_orientation,
            )
        sizes = tuple(self._catalog_bounds(image_id) for image_id in source_ids)
        canvas_width = max(bounds.width for bounds in sizes)
        canvas_height = max(bounds.height for bounds in sizes)
        record = CompositionRecord(
            composition_id=composition_id,
            origin=CompositionOrigin.EXPLICIT,
            title=self._explicit_title(title, source_ids, path_lookup),
            canvas_bounds=QRectF(0.0, 0.0, canvas_width, canvas_height),
            navigation_image_id=source_ids[0],
            comparison=comparison,
        )
        self._records[composition_id] = record
        self._layer_notification_depth += 1
        try:
            self._layers.ensure_composition(
                composition_id,
                tuple(
                    CompositionLayerInstance(
                        layer_id=uuid.uuid4(),
                        source=self._catalog_source(image_id),
                        transform=LayerTransform(),
                        visible=index == 0,
                        interaction=LayerInteractionPolicy(
                            reorderable=False,
                            removable=False,
                        ),
                        role="content" if index == 0 else "comparison-source",
                    )
                    for index, image_id in enumerate(source_ids)
                ),
            )
        finally:
            self._layer_notification_depth -= 1
        self._order.append(composition_id)
        self._active_id = composition_id
        self._touch()
        return record

    def compose_scene(
        self,
        request: CompositionRequest,
        *,
        catalog_contains: Callable[[uuid.UUID], bool],
        activate: bool,
    ) -> CompositionRecord:
        """Create or replace a stored layered scene composition."""
        record, layers = self._request_composer.document_from_request(
            request,
            catalog_contains=catalog_contains,
        )
        existing = self._records.get(record.composition_id)
        if existing is not None and not existing.policy.removable:
            raise ValueError("default catalog compositions cannot be replaced")
        if existing is not None:
            self._edit_history.clear_scope(record.composition_id)
        self._records[record.composition_id] = record
        self._layer_notification_depth += 1
        try:
            self._layers.replace_layers(record.composition_id, layers)
        finally:
            self._layer_notification_depth -= 1
        if record.composition_id not in self._order:
            self._order.append(record.composition_id)
        if activate:
            self._active_id = record.composition_id
        self._touch()
        return record

    def compose_scene_from_template(
        self,
        template: CompositionTemplate,
        bindings: TemplateBindings,
        *,
        catalog_contains: Callable[[uuid.UUID], bool],
        activate: bool,
    ) -> CompositionRecord:
        """Expand a host-owned template into a stored layered composition."""
        return self.compose_scene(
            self._request_composer.request_from_template(template, bindings),
            catalog_contains=catalog_contains,
            activate=activate,
        )

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

    def update_scene_layer_placement(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        placement: LayerPlacement,
    ) -> bool:
        """Replace placement for one stored scene layer."""
        record = self._records.get(scene_id)
        instance = self._layers.layer(scene_id, layer_id)
        if (
            record is None
            or instance is None
            or instance.source.kind != "catalog-image"
        ):
            return False
        changed = self._layers.update_transform(
            scene_id,
            layer_id,
            LayerTransform.from_placement(
                self._catalog_bounds(instance.source.image_id), placement
            ),
        )
        if changed:
            self._touch()
        return changed

    def update_scene_layer_transform(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        transform: LayerTransform,
    ) -> bool:
        """Replace exact geometry for one stored composition layer."""
        record = self._records.get(scene_id)
        if record is None or self._layers.layer(scene_id, layer_id) is None:
            return False
        changed = self._layers.update_transform(scene_id, layer_id, transform)
        if changed:
            self._touch()
        return changed

    def open_composition(self, composition_id: uuid.UUID) -> CompositionRecord:
        """Activate and return an existing composition record."""
        record = self.record(composition_id)
        if self._active_id != composition_id:
            self._active_id = composition_id
            self._touch()
        return record

    def open_default_for_image(self, image_id: uuid.UUID) -> CompositionRecord:
        """Activate the generated default composition for ``image_id``."""
        composition_id = self._default_by_image_id.get(image_id)
        if composition_id is None:
            raise KeyError("catalog image does not have a default composition")
        return self.open_composition(composition_id)

    def remove_composition(self, composition_id: uuid.UUID) -> bool:
        """Remove an explicit or layered composition and update active selection."""
        record = self.record(composition_id)
        if not record.policy.removable:
            raise ValueError("composition policy prevents removal")
        self._records.pop(composition_id, None)
        self._layers.remove_composition(composition_id)
        self._edit_history.clear_scope(composition_id)
        self._order = [item for item in self._order if item != composition_id]
        if self._active_id == composition_id:
            self._active_id = self._order[0] if self._order else None
        self._touch()
        return True

    def set_catalog_comparison(
        self,
        source_id: uuid.UUID,
        *,
        path: Path | None,
    ) -> bool:
        """Set a catalog comparison source on the active composition."""
        record = self.active_record()
        if record is None:
            raise RuntimeError("no active composition")
        if not record.policy.comparison_enabled:
            raise RuntimeError("comparison is disabled by the composition policy")
        current = record.comparison
        comparison = CompositionComparison(
            source_id=source_id,
            source_path=path,
            source_kind="catalog",
            split_position=(
                current.split_position if current else self._default_split_position
            ),
            orientation=current.orientation if current else self._default_orientation,
        )
        return self._replace_active_comparison(comparison)

    def clear_comparison(self) -> bool:
        """Clear comparison settings from the active composition."""
        record = self.active_record()
        if record is None:
            return False
        if not record.policy.comparison_enabled:
            raise RuntimeError("comparison is disabled by the composition policy")
        if record.comparison is None:
            return False
        return self._replace_active_comparison(None)

    def set_comparison_split(
        self,
        position: float,
        orientation: ComparisonOrientation,
    ) -> bool:
        """Update comparison split state on the active composition."""
        record = self.active_record()
        if record is not None and not record.policy.comparison_enabled:
            raise RuntimeError("comparison is disabled by the composition policy")
        default_changed = (
            self._default_split_position != position
            or self._default_orientation != orientation
        )
        self._default_split_position = position
        self._default_orientation = orientation
        if record is None or record.comparison is None:
            if default_changed:
                self._touch()
            return default_changed
        comparison = record.comparison.with_split(position, orientation)
        return self._replace_active_comparison(comparison)

    def active_record(self) -> CompositionRecord | None:
        """Return the active composition record, if any."""
        if self._active_id is None:
            return None
        return self._records.get(self._active_id)

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

    def current_composition_id(self) -> uuid.UUID | None:
        """Return the active composition ID."""
        return self._active_id

    def default_composition_for_image(self, image_id: uuid.UUID) -> uuid.UUID | None:
        """Return the generated default composition ID for a catalog image."""
        return self._default_by_image_id.get(image_id)

    def is_generated_default(self, composition_id: uuid.UUID) -> bool:
        """Return whether catalog navigation generated this compatibility document."""
        return composition_id in self._default_by_image_id.values()

    def image_id_for_default_composition(
        self, composition_id: uuid.UUID
    ) -> uuid.UUID | None:
        """Return the catalog image owning a generated composition."""
        record = self._records.get(composition_id)
        if record is None or composition_id not in self._default_by_image_id.values():
            return None
        return record.navigation_image_id

    def comparison_state(self) -> ComparisonState:
        """Return public comparison state for the active composition."""
        comparison = self._active_comparison()
        if comparison is None:
            return ComparisonState(
                enabled=False,
                source_id=None,
                source_path=None,
                source_kind=None,
                split_position=self._default_split_position,
                orientation=self._default_orientation,
            )
        return ComparisonState(
            enabled=True,
            source_id=comparison.source_id,
            source_path=comparison.source_path,
            source_kind=comparison.source_kind,
            split_position=comparison.split_position,
            orientation=comparison.orientation,
        )

    def snapshot(self) -> CompositionSnapshot:
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
            current_composition_id=self._active_id,
        )

    def remove_catalog_images(self, image_ids: set[uuid.UUID]) -> bool:
        """Remove compositions and comparison sources tied to missing catalog images."""
        return self._remove_invalid_catalog_references(
            set(self._catalog_ids()) - image_ids
        )

    def revision(self) -> int:
        """Return a revision for render-relevant composition state."""
        return self._revision

    def _replace_active_comparison(
        self, comparison: CompositionComparison | None
    ) -> bool:
        """Replace active comparison state and report whether it changed."""
        record = self.active_record()
        if record is None:
            raise RuntimeError("no active composition")
        if record.comparison == comparison:
            return False
        self._records[record.composition_id] = record.with_comparison(comparison)
        self._touch()
        return True

    def _active_comparison(self) -> CompositionComparison | None:
        """Return the active composition comparison payload."""
        record = self.active_record()
        if record is None:
            return None
        return record.comparison

    def _remove_invalid_catalog_references(
        self, valid_ids: set[uuid.UUID], *, touch: bool = True
    ) -> bool:
        """Drop records that reference catalog images outside ``valid_ids``."""
        changed = False
        for image_id, composition_id in list(self._default_by_image_id.items()):
            if image_id in valid_ids:
                continue
            self._default_by_image_id.pop(image_id, None)
            self._records.pop(composition_id, None)
            self._layers.remove_composition(composition_id)
            self._edit_history.clear_scope(composition_id)
            changed = True
        for composition_id, record in list(self._records.items()):
            if composition_id in self._default_by_image_id.values():
                continue
            layers = self._layers.layers_for_composition(composition_id)
            retained = tuple(
                layer
                for layer in layers
                if not isinstance(layer.source, CatalogImageReference)
                or layer.source.image_id in valid_ids
            )
            if retained != layers:
                if record.policy.remove_if_catalog_resource_missing:
                    self._records.pop(composition_id, None)
                    self._layers.remove_composition(composition_id)
                    self._edit_history.clear_scope(composition_id)
                    changed = True
                    continue
                self._layers.replace_layers(composition_id, retained)
                changed = True
            comparison = record.comparison
            if (
                comparison is not None
                and comparison.source_kind == "catalog"
                and comparison.source_id not in valid_ids
            ):
                self._records[composition_id] = record.with_comparison(None)
                changed = True
        self._order = [
            composition_id
            for composition_id in self._order
            if composition_id in self._records
        ]
        if self._active_id is not None and self._active_id not in self._records:
            self._active_id = self._order[0] if self._order else None
            changed = True
        if changed and touch:
            self._touch()
        return changed

    def _catalog_ids(self) -> tuple[uuid.UUID, ...]:
        """Return catalog IDs referenced by existing compositions."""
        image_ids: list[uuid.UUID] = []
        for record in self._records.values():
            image_ids.extend(
                layer.source.image_id
                for layer in self._layers.layers_for_composition(record.composition_id)
                if isinstance(layer.source, CatalogImageReference)
            )
            comparison = record.comparison
            if comparison is not None and comparison.source_kind == "catalog":
                image_ids.append(comparison.source_id)
        return tuple(image_ids)

    def _entry(self, record: CompositionRecord) -> CompositionEntry:
        """Convert an internal record into a public snapshot entry."""
        instances = self._layers.layers_for_composition(record.composition_id)
        source_image_ids = self._unique_source_ids(
            layer.source.image_id
            for layer in instances
            if isinstance(layer.source, CatalogImageReference)
        )
        return CompositionEntry(
            composition_id=record.composition_id,
            kind=record.origin.value,
            title=record.title,
            source_image_ids=source_image_ids,
            current_image_id=record.navigation_image_id,
            comparison=self._state_for_record(record),
            scene_layer_count=len(instances),
            scene_bounds=QRectF(record.canvas_bounds),
            layers=tuple(self._layer_entry(instance) for instance in instances),
            policy=public_document_policy(record.policy),
        )

    @staticmethod
    def _layer_entry(instance: CompositionLayerInstance) -> CompositionLayerEntry:
        """Detach one ordered layer instance for composition browser clients."""
        return CompositionLayerEntry(
            layer_id=instance.layer_id,
            source_kind=instance.source.kind,
            source_id=instance.source.resource_id,
            label=instance.label,
            role=instance.role,
            visible=instance.visible,
            opacity=instance.opacity,
            interaction=public_layer_policy(instance.interaction),
            transform=instance.transform.to_qtransform(),
        )

    def _state_for_record(self, record: CompositionRecord) -> ComparisonState:
        """Return comparison state for one record."""
        comparison = record.comparison
        if comparison is None:
            return ComparisonState(
                enabled=False,
                source_id=None,
                source_path=None,
                source_kind=None,
                split_position=self._default_split_position,
                orientation=self._default_orientation,
            )
        return ComparisonState(
            enabled=True,
            source_id=comparison.source_id,
            source_path=comparison.source_path,
            source_kind=comparison.source_kind,
            split_position=comparison.split_position,
            orientation=comparison.orientation,
        )

    @staticmethod
    def _unique_source_ids(image_ids: Iterable[uuid.UUID]) -> tuple[uuid.UUID, ...]:
        """Return image IDs in first-use order with duplicates removed."""
        seen: set[uuid.UUID] = set()
        ordered: list[uuid.UUID] = []
        for image_id in image_ids:
            if image_id in seen:
                continue
            seen.add(image_id)
            ordered.append(image_id)
        return tuple(ordered)

    def _touch(self) -> None:
        """Advance the composition revision."""
        self._revision += 1

    def _handle_layer_store_changed(self, composition_id: uuid.UUID) -> None:
        """Publish only stack mutations belonging to a complete stored record."""
        if (
            self._layers_changed is not None
            and self._layer_notification_depth == 0
            and composition_id in self._records
            and composition_id in self._order
        ):
            self._layers_changed(composition_id)

    def _catalog_bounds(self, image_id: uuid.UUID) -> RasterBounds:
        """Return positive catalog-local bounds for one composed source."""
        if self._catalog_size is None:
            raise RuntimeError("catalog size lookup is not configured")
        size = self._catalog_size(image_id)
        if size.width() <= 0 or size.height() <= 0:
            raise KeyError("scene layer image_id does not resolve to a catalog image")
        return RasterBounds.from_size(size)

    def _catalog_source(self, image_id: uuid.UUID) -> LayerSourceReference:
        """Build one catalog-domain source reference through the injected owner."""
        if self._catalog_reference is None:
            raise RuntimeError("catalog source-reference factory is not configured")
        return self._catalog_reference(image_id)

    @staticmethod
    def _default_title(path: Path | None, index: int) -> str:
        """Return the generated title for a default image composition."""
        if path is not None:
            return path.name
        return f"Image {index + 1}"

    @staticmethod
    def _explicit_title(
        title: str | None,
        source_ids: tuple[uuid.UUID, ...],
        path_lookup: Callable[[uuid.UUID], Path | None],
    ) -> str:
        """Return a host-provided or generated title for an explicit composition."""
        if title is not None and title.strip():
            return title.strip()
        labels = [
            (
                path.name
                if (path := path_lookup(image_id)) is not None
                else image_id.hex[:8]
            )
            for image_id in source_ids
        ]
        return " / ".join(labels)
