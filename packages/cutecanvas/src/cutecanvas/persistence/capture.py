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
"""Capture one document's complete transitive project-resource closure."""

from __future__ import annotations

import uuid

from ..composition.resource_references import instance_resources
from ..composition.service import CompositionService
from ..masks.mask import MaskAssetStore
from ..placed.store import PlacedAssetStore
from ..raster.assets import EditableRasterAssetStore
from ..resources import ProjectResourceKind, ProjectResourceReference
from ..vector.store import VectorAssetStore
from .model import CompositionArchiveSnapshot


def capture_composition(
    root_document_id: uuid.UUID,
    compositions: CompositionService,
    masks: MaskAssetStore | None,
    rasters: EditableRasterAssetStore,
    placed_assets: PlacedAssetStore,
    vectors: VectorAssetStore,
) -> CompositionArchiveSnapshot:
    """Return a detached archive for a document and every nested dependency."""
    return capture_document(
        (root_document_id,),
        compositions,
        masks,
        rasters,
        placed_assets,
        vectors,
    )


def capture_document(
    root_document_ids: tuple[uuid.UUID, ...],
    compositions: CompositionService,
    masks: MaskAssetStore | None,
    rasters: EditableRasterAssetStore,
    placed_assets: PlacedAssetStore,
    vectors: VectorAssetStore,
) -> CompositionArchiveSnapshot:
    """Return every root and their deduplicated transitive resource closures."""
    if not root_document_ids:
        raise ValueError("document archive requires at least one root")
    if len(set(root_document_ids)) != len(root_document_ids):
        raise ValueError("document archive roots must be unique")
    resources = rasters.resources
    documents = {}
    layer_stacks = {}
    resource_records = {}
    mask_surfaces = {}
    color_surfaces = {}
    imported_snapshots = {}
    vector_documents = {}
    pending_documents = list(reversed(root_document_ids))
    pending_resources: list[uuid.UUID] = []
    visited_documents: set[uuid.UUID] = set()
    visited_resources: set[uuid.UUID] = set()

    while pending_documents:
        document_id = pending_documents.pop()
        if document_id in visited_documents:
            continue
        document = compositions.record(document_id)
        layers = compositions.layers.layers_for_composition(document_id)
        visited_documents.add(document_id)
        documents[document_id] = document
        layer_stacks[document_id] = layers
        pending_resources.extend(
            source.resource_id
            for layer in layers
            for source in instance_resources(layer)
            if isinstance(source, ProjectResourceReference)
        )
        pending_resources.append(document_id)

        while pending_resources:
            resource_id = pending_resources.pop()
            if resource_id in visited_resources:
                continue
            resource = resources.get(resource_id)
            if resource is None:
                raise KeyError(f"project resource {resource_id} does not exist")
            visited_resources.add(resource_id)
            resource_records[resource_id] = resource
            pending_resources.extend(resource.dependencies)
            if resource.kind is ProjectResourceKind.COMPOSITION:
                pending_documents.append(resource_id)
            elif resource.kind is ProjectResourceKind.COVERAGE:
                if masks is None:
                    raise RuntimeError("coverage persistence requires the mask feature")
                layer = masks.get_layer(resource_id)
                if layer is None:
                    raise KeyError(f"coverage resource {resource_id} has no payload")
                mask_surfaces[resource_id] = layer.coverage.state_snapshot()
            elif resource.kind is ProjectResourceKind.RASTER:
                asset = rasters.get(resource_id)
                if asset is None:
                    raise KeyError(f"raster resource {resource_id} has no payload")
                color_surfaces[resource_id] = asset.surface.sparse_snapshot()
            elif resource.kind in {
                ProjectResourceKind.IMPORTED_RASTER,
                ProjectResourceKind.LINKED_RASTER,
            }:
                snapshot = placed_assets.get(resource_id)
                if snapshot is None:
                    raise KeyError(
                        f"imported raster resource {resource_id} has no payload"
                    )
                imported_snapshots[resource_id] = snapshot
            elif resource.kind is ProjectResourceKind.VECTOR:
                document = vectors.get(resource_id)
                if document is None:
                    raise KeyError(f"vector resource {resource_id} has no payload")
                vector_documents[resource_id] = document

    return CompositionArchiveSnapshot(
        root_document_id=root_document_ids[0],
        documents=documents,
        layer_stacks=layer_stacks,
        resources=resource_records,
        masks=mask_surfaces,
        rasters=color_surfaces,
        placed_assets=imported_snapshots,
        vectors=vector_documents,
        root_document_ids=root_document_ids,
    )
