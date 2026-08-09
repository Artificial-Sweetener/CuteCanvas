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
"""Durable resource and composition owners shared by every document view."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from ..composition import CompositionService
from ..placed.history import PlacedAssetEdit, PlacedAssetEditOwner
from ..placed.store import PlacedAssetStore
from ..raster.assets import EditableRasterAssetStore
from ..raster.paint_history import RasterPaintHistory
from ..raster.structure_mutations import (
    ColorRasterStructureEdit,
    ColorRasterStructureHistoryOwner,
)
from ..scene.mapping_edit import LayerMappingEdit, LayerMappingHistoryOwner
from ..selection import PixelSelectionEdit, PixelSelectionService, PixelSelectionState
from .composition_resources import CompositionResourceOwner
from .image_documents import ImageDocumentWorkflow
from .layer_operations import LayerResourceOperations, ResourceForkOwner
from .lifecycle import ProjectResourceLifecycleOwner
from .model import ProjectResourceKind
from .store import ProjectResourceStore


@dataclass(frozen=True, slots=True)
class DocumentResourceCore:
    """Group durable owners whose lifetime is exactly one canvas document."""

    resources: ProjectResourceStore
    lifecycle: ProjectResourceLifecycleOwner
    compositions: CompositionService
    editable_raster_assets: EditableRasterAssetStore
    placed_assets: PlacedAssetStore
    image_documents: ImageDocumentWorkflow
    layer_operations: LayerResourceOperations
    pixel_selection: PixelSelectionService
    raster_paint_history: RasterPaintHistory

    @classmethod
    def create(
        cls,
        *,
        history_changed: Callable[[uuid.UUID], None],
        layers_changed: Callable[[uuid.UUID], None],
        pixel_selection_changed: Callable[[PixelSelectionState], None],
        resource_changed: Callable[[uuid.UUID], None],
    ) -> DocumentResourceCore:
        """Construct one complete durable identity, payload, and history graph."""
        resources = ProjectResourceStore()
        composition_resources = CompositionResourceOwner(resources)
        compositions = CompositionService(
            history_changed=history_changed,
            layers_changed=layers_changed,
            source_kind=lambda source: _resolved_source_kind(resources, source),
            document_resources=composition_resources,
        )
        lifecycle = ProjectResourceLifecycleOwner(resources)
        compositions.resource_lifetime.register_owner(lifecycle)

        raster_assets = EditableRasterAssetStore(resources)
        lifecycle.register(ProjectResourceKind.RASTER, raster_assets.remove)
        placed_assets = PlacedAssetStore(resources)
        placed_history = PlacedAssetEditOwner(placed_assets, resource_changed)
        compositions.edit_controller.register_handler(
            PlacedAssetEdit,
            undo=placed_history.undo,
            redo=placed_history.redo,
        )
        image_documents = ImageDocumentWorkflow(
            compositions=compositions,
            imported_rasters=placed_assets,
        )
        layer_operations = LayerResourceOperations(
            resources=resources,
            layers=compositions.layers,
            edits=compositions.layer_edits,
        )
        _install_resource_lifetime(
            compositions,
            raster_assets,
            placed_assets,
            lifecycle,
            layer_operations,
        )
        pixel_selection = PixelSelectionService(
            changed=pixel_selection_changed,
            record_edit=compositions.edit_controller.record_applied,
        )
        compositions.edit_controller.register_handler(
            PixelSelectionEdit,
            undo=pixel_selection.undo_edit,
            redo=pixel_selection.redo_edit,
        )
        mapping_history = LayerMappingHistoryOwner(compositions.layers)
        compositions.edit_controller.register_handler(
            LayerMappingEdit,
            undo=mapping_history.undo,
            redo=mapping_history.redo,
        )
        raster_paint_history = RasterPaintHistory(
            assets=raster_assets,
            edits=compositions.edit_controller,
            changed=lambda raster_id, _bounds: resource_changed(raster_id),
            structure_changed=resource_changed,
        )
        raster_structure_history = ColorRasterStructureHistoryOwner(
            raster_assets,
            resource_changed,
        )
        compositions.edit_controller.register_handler(
            ColorRasterStructureEdit,
            undo=raster_structure_history.undo,
            redo=raster_structure_history.redo,
        )
        return cls(
            resources,
            lifecycle,
            compositions,
            raster_assets,
            placed_assets,
            image_documents,
            layer_operations,
            pixel_selection,
            raster_paint_history,
        )


def _install_resource_lifetime(
    compositions: CompositionService,
    raster_assets: EditableRasterAssetStore,
    placed_assets: PlacedAssetStore,
    lifecycle: ProjectResourceLifecycleOwner,
    layer_operations: LayerResourceOperations,
) -> None:
    """Register durable payload cloning and final-release routes."""
    layer_operations.register_fork_owner(
        ProjectResourceKind.RASTER,
        ResourceForkOwner(
            fork=raster_assets.fork,
            remove=raster_assets.remove,
        ),
    )
    imported_fork_owner = ResourceForkOwner(
        fork=placed_assets.fork,
        remove=placed_assets.remove,
    )
    for kind in (
        ProjectResourceKind.IMPORTED_RASTER,
        ProjectResourceKind.LINKED_RASTER,
    ):
        layer_operations.register_fork_owner(kind, imported_fork_owner)
        lifecycle.register(kind, placed_assets.remove)
    layer_operations.register_fork_owner(
        ProjectResourceKind.COMPOSITION,
        ResourceForkOwner(
            fork=compositions.fork_composition,
            remove=lambda resource_id: _remove_forked_composition(
                compositions,
                resource_id,
            ),
        ),
    )


def _remove_forked_composition(
    compositions: CompositionService,
    composition_id,
) -> bool:
    """Remove one unreferenced nested composition after a failed fork."""
    if composition_id not in compositions.composition_ids():
        return False
    compositions.remove_composition(composition_id)
    return True


def _resolved_source_kind(
    resources: ProjectResourceStore,
    source: object,
) -> str:
    """Return document-resource kind while preserving foreign source routing."""
    from .model import ProjectResourceReference

    if isinstance(source, ProjectResourceReference):
        record = resources.resolve(source)
        if record is not None:
            return record.kind.value
    return str(getattr(source, "kind", "unknown"))
