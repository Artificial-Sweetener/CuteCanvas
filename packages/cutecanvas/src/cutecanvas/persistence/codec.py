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
"""Versioned, validated, and atomic private composition archive I/O."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
import zipfile
from pathlib import Path

import numpy as np
from PySide6.QtCore import QRectF, QSize
from qpane.sdk.raster import (
    numpy_to_qimage_argb32,
    qimage_to_numpy_argb32,
)
from qpane.sdk.scene import RasterBounds
from qpane.sdk.vector import VectorDocument, VectorObject

from cutecanvas.coverage import (
    CoverageAssetSnapshot,
    CoverageDocument,
    CoverageSnapshot,
)
from cutecanvas.types import RasterExtentPolicy

from ..composition.layers import CompositionLayerInstance
from ..composition.model import (
    CompositionDocumentPolicy,
    CompositionOrigin,
    CompositionRecord,
)
from ..composition.resource_references import instance_resources
from ..placed.model import (
    FileFingerprint,
    PlacedAssetMode,
    PlacedAssetSnapshot,
    PlacedAssetStatus,
)
from ..raster.color_surface import ColorRasterSnapshot
from ..raster.sparse_grid import (
    SparseRasterGrid,
    SparseRasterSnapshot,
    SparseRasterTile,
)
from ..resources import (
    ProjectResourceKind,
    ProjectResourceRecord,
    ProjectResourceReference,
)
from .coverage_codec import (
    decode_coverage_document,
    encode_coverage_document,
    write_coverage_pixels,
)
from .layer_codec import decode_layer, encode_layer
from .legacy_shared_edges import recover_version_14_shared_edges
from .model import CompositionArchiveSnapshot
from .vector_object_codec import decode_vector_object, encode_vector_object

_FORMAT = "qpane-composition"
_VERSION = 15
_MIGRATABLE_VERSIONS = frozenset(range(2, _VERSION + 1))
_MAX_RASTER_PIXELS = 268_435_456
_MAX_COLOR_RASTER_BYTES = _MAX_RASTER_PIXELS * 4
_MAX_VECTOR_OBJECTS = 100_000
_MAX_VECTOR_POINTS = 4_000_000


class CompositionArchiveCodec:
    """Encode and decode one private CuteCanvas composition archive version."""

    def write(self, archive: CompositionArchiveSnapshot, path: Path) -> None:
        """Atomically write ``archive`` to ``path`` as a ZIP container."""
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix=f".{destination.name}.",
                suffix=".tmp",
                dir=destination.parent,
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
            with zipfile.ZipFile(
                temporary_path,
                "w",
                compression=zipfile.ZIP_DEFLATED,
            ) as container:
                container.writestr(
                    "manifest.json",
                    json.dumps(self._manifest(archive), separators=(",", ":")),
                )
                for mask_id, snapshot in archive.masks.items():
                    self._write_sparse_tiles(
                        container,
                        "masks",
                        mask_id,
                        snapshot.raster,
                    )
                    write_coverage_pixels(container, mask_id, snapshot.retained)
                for raster_id, snapshot in archive.rasters.items():
                    self._write_sparse_tiles(container, "rasters", raster_id, snapshot)
                for asset_id, snapshot in archive.placed_assets.items():
                    if snapshot.image is None or (
                        snapshot.mode is PlacedAssetMode.LINKED
                        and not snapshot.keep_fallback
                    ):
                        continue
                    with container.open(f"placed/{asset_id}.npy", "w") as stream:
                        np.save(
                            stream,
                            qimage_to_numpy_argb32(snapshot.image),
                            allow_pickle=False,
                        )
            os.replace(temporary_path, destination)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _write_sparse_tiles(
        container: zipfile.ZipFile,
        domain: str,
        resource_id: uuid.UUID,
        snapshot: SparseRasterSnapshot,
    ) -> None:
        """Write only allocated authoritative tiles for one sparse resource."""
        for index, tile in enumerate(snapshot.tiles):
            with container.open(f"{domain}/{resource_id}/{index}.npy", "w") as stream:
                np.save(stream, tile.pixels, allow_pickle=False)

    def read(self, path: Path) -> CompositionArchiveSnapshot:
        """Read and fully validate an archive before returning domain values."""
        with zipfile.ZipFile(Path(path), "r") as container:
            manifest = json.loads(container.read("manifest.json"))
            version = self._validate_header(manifest)
            snapshot = (
                self._read_version_two(container, manifest)
                if version == 2
                else self._read_resource_table(container, manifest, version=version)
            )
            snapshot = (
                recover_version_14_shared_edges(snapshot) if version == 14 else snapshot
            )
        self._validate_references(snapshot)
        return snapshot

    @staticmethod
    def _manifest(archive: CompositionArchiveSnapshot) -> dict[str, object]:
        """Return the JSON manifest for ``archive``."""
        return {
            "format": _FORMAT,
            "version": _VERSION,
            "root_document_id": str(archive.root_document_id),
            "root_document_ids": [
                str(document_id) for document_id in archive.root_document_ids
            ],
            "documents": [
                {
                    "document": CompositionArchiveCodec._encode_document(
                        archive.documents[document_id]
                    ),
                    "instances": [
                        encode_layer(layer)
                        for layer in archive.layer_stacks[document_id]
                    ],
                }
                for document_id in sorted(archive.documents, key=str)
            ],
            "resources": CompositionArchiveCodec._encode_resources(archive),
        }

    @staticmethod
    def _encode_document(document: CompositionRecord) -> dict[str, object]:
        """Encode composition-owned document values independently of resources."""
        bounds = document.canvas_bounds
        return {
            "composition_id": str(document.composition_id),
            "origin": document.origin.value,
            "title": document.title,
            "canvas_bounds": [
                bounds.x(),
                bounds.y(),
                bounds.width(),
                bounds.height(),
            ],
            "policy": {
                "removable": document.policy.removable,
            },
        }

    @staticmethod
    def _encode_resources(
        archive: CompositionArchiveSnapshot,
    ) -> list[dict[str, object]]:
        """Return one deduplicated resource-table entry per referenced source."""
        resources: list[dict[str, object]] = []
        for resource_id in sorted(archive.resources, key=str):
            record = archive.resources[resource_id]
            entry = _project_resource_manifest(record)
            if record.kind is ProjectResourceKind.COVERAGE:
                entry["payload"] = _coverage_manifest(
                    resource_id,
                    archive.masks[resource_id],
                )
            elif record.kind is ProjectResourceKind.RASTER:
                entry["payload"] = _raster_manifest(
                    resource_id,
                    archive.rasters[resource_id],
                )
            elif record.kind in {
                ProjectResourceKind.IMPORTED_RASTER,
                ProjectResourceKind.LINKED_RASTER,
            }:
                entry["payload"] = _placed_manifest(
                    resource_id,
                    archive.placed_assets[resource_id],
                )
            elif record.kind is ProjectResourceKind.VECTOR:
                entry["payload"] = _vector_manifest(archive.vectors[resource_id])
            resources.append(entry)
        return resources

    @classmethod
    def _read_version_two(
        cls,
        container: zipfile.ZipFile,
        manifest: dict[str, object],
    ) -> CompositionArchiveSnapshot:
        """Migrate one validated flat version-2 manifest into current values."""
        image_id = uuid.UUID(str(manifest["image_id"]))
        layer_items = manifest["layers"]
        mask_items = manifest["masks"]
        raster_items = manifest.get("rasters", {})
        assert isinstance(layer_items, list)
        assert isinstance(mask_items, dict)
        assert isinstance(raster_items, dict)
        layers = tuple(
            decode_layer(item, legacy_version_two=True) for item in layer_items
        )
        masks = {
            uuid.UUID(mask_id): cls._decode_mask(container, mask_id, item)
            for mask_id, item in mask_items.items()
        }
        rasters = {
            uuid.UUID(raster_id): cls._decode_raster(container, raster_id, item)
            for raster_id, item in raster_items.items()
        }
        return CompositionArchiveSnapshot(
            root_document_id=image_id,
            documents={
                image_id: cls._legacy_document(
                    image_id,
                    image_id,
                    layers,
                    masks,
                    rasters,
                    {},
                )
            },
            layer_stacks={image_id: layers},
            resources={
                **{
                    raster_id: ProjectResourceRecord(
                        raster_id,
                        ProjectResourceKind.RASTER,
                        True,
                    )
                    for raster_id in rasters
                },
                image_id: ProjectResourceRecord(
                    image_id,
                    ProjectResourceKind.COMPOSITION,
                    True,
                    dependencies=frozenset(
                        source.resource_id
                        for layer in layers
                        for source in instance_resources(layer)
                        if isinstance(source, ProjectResourceReference)
                    ),
                ),
            },
            masks=masks,
            rasters=rasters,
            placed_assets={},
            vectors={},
        )

    @classmethod
    def _read_resource_table(
        cls,
        container: zipfile.ZipFile,
        manifest: dict[str, object],
        *,
        version: int,
    ) -> CompositionArchiveSnapshot:
        """Decode one validated current resource-table manifest."""
        document_records: dict[uuid.UUID, CompositionRecord] = {}
        document_layers: dict[
            uuid.UUID,
            tuple[CompositionLayerInstance, ...],
        ] = {}
        if version >= 11:
            document_items = manifest["documents"]
            assert isinstance(document_items, list)
            for item in document_items:
                if not isinstance(item, dict):
                    raise TypeError("archive document entries must be objects")
                document = cls._decode_document(item.get("document"))
                instances = item.get("instances")
                if not isinstance(instances, list):
                    raise TypeError("archive document instances must be a list")
                if document.composition_id in document_records:
                    raise ValueError("archive document identities must be unique")
                document_records[document.composition_id] = document
                document_layers[document.composition_id] = tuple(
                    decode_layer(layer) for layer in instances
                )
            instance_items = [
                layer for item in document_items for layer in item["instances"]
            ]
        else:
            instance_items = manifest["instances"]
        resource_items = manifest["resources"]
        assert isinstance(instance_items, list)
        assert isinstance(resource_items, list)
        layers = tuple(decode_layer(item) for item in instance_items)
        masks: dict[uuid.UUID, CoverageAssetSnapshot] = {}
        rasters: dict[uuid.UUID, SparseRasterSnapshot] = {}
        placed_assets: dict[uuid.UUID, PlacedAssetSnapshot] = {}
        vectors: dict[uuid.UUID, VectorDocument] = {}
        project_resources: dict[uuid.UUID, ProjectResourceRecord] = {}
        resource_keys: set[tuple[str, uuid.UUID]] = set()
        for item in resource_items:
            if not isinstance(item, dict):
                raise TypeError("resource entries must be objects")
            kind = str(item["kind"])
            resource_id = uuid.UUID(str(item["resource_id"]))
            key = (kind, resource_id)
            if key in resource_keys:
                raise ValueError("archive resource identities must be unique")
            resource_keys.add(key)
            payload = item.get("payload")
            if kind in {"mask", ProjectResourceKind.COVERAGE.value}:
                masks[resource_id] = cls._decode_mask(
                    container,
                    str(resource_id),
                    payload,
                    retained=version >= 9,
                    authored=version >= 12,
                )
                project_resources[resource_id] = _decode_project_resource(
                    item,
                    resource_id,
                    ProjectResourceKind.COVERAGE,
                    editable=True,
                    current=version >= 10 and kind != "mask",
                )
            elif kind == "raster":
                rasters[resource_id] = cls._decode_raster(
                    container, str(resource_id), payload
                )
                project_resources[resource_id] = _decode_project_resource(
                    item,
                    resource_id,
                    ProjectResourceKind.RASTER,
                    editable=True,
                    current=version >= 10,
                )
            elif kind in {"placed-asset", "imported-raster", "linked-raster"}:
                placed = cls._decode_placed(
                    container,
                    str(resource_id),
                    payload,
                )
                placed_assets[resource_id] = placed
                legacy_kind = (
                    ProjectResourceKind.LINKED_RASTER
                    if placed.mode is PlacedAssetMode.LINKED
                    else ProjectResourceKind.IMPORTED_RASTER
                )
                project_resources[resource_id] = _decode_project_resource(
                    item,
                    resource_id,
                    (
                        ProjectResourceKind(kind)
                        if kind != "placed-asset"
                        else legacy_kind
                    ),
                    editable=False,
                    current=version >= 10,
                )
            elif kind == "vector":
                vectors[resource_id] = cls._decode_vector(resource_id, payload)
                project_resources[resource_id] = _decode_project_resource(
                    item,
                    resource_id,
                    ProjectResourceKind.VECTOR,
                    editable=True,
                    current=version >= 10,
                )
            elif kind == ProjectResourceKind.COMPOSITION.value:
                if payload is not None:
                    raise ValueError("composition resources must not contain payloads")
                project_resources[resource_id] = _decode_project_resource(
                    item,
                    resource_id,
                    ProjectResourceKind.COMPOSITION,
                    editable=True,
                    current=version >= 10,
                )
            else:
                raise ValueError(f"unsupported project resource kind: {kind}")
        _validate_resource_table_references(
            layers,
            resource_keys,
            project_resources,
        )
        if version >= 11:
            root_document_id = uuid.UUID(str(manifest["root_document_id"]))
            root_values = manifest.get("root_document_ids")
            root_document_ids = (
                tuple(uuid.UUID(str(value)) for value in root_values)
                if isinstance(root_values, list)
                else (root_document_id,)
            )
            documents = document_records
            layer_stacks = document_layers
        else:
            document = (
                cls._decode_document(manifest.get("document"))
                if version >= 8
                else cls._legacy_document(
                    uuid.UUID(str(manifest["composition_id"])),
                    uuid.UUID(str(manifest["base_image_id"])),
                    layers,
                    masks,
                    rasters,
                    vectors,
                )
            )
            root_document_id = document.composition_id
            root_document_ids = (root_document_id,)
            documents = {root_document_id: document}
            layer_stacks = {root_document_id: layers}
            project_resources[root_document_id] = ProjectResourceRecord(
                root_document_id,
                ProjectResourceKind.COMPOSITION,
                True,
                dependencies=frozenset(
                    source.resource_id
                    for layer in layers
                    for source in instance_resources(layer)
                    if isinstance(source, ProjectResourceReference)
                    and source.resource_id != root_document_id
                ),
            )
        return CompositionArchiveSnapshot(
            root_document_id=root_document_id,
            documents=documents,
            layer_stacks=layer_stacks,
            resources=project_resources,
            masks=masks,
            rasters=rasters,
            placed_assets=placed_assets,
            vectors=vectors,
            root_document_ids=root_document_ids,
        )

    @staticmethod
    def _decode_document(item: object) -> CompositionRecord:
        """Validate and decode one current composition document payload."""
        if not isinstance(item, dict):
            raise TypeError("archive document must be an object")
        bounds_values = item.get("canvas_bounds")
        if not isinstance(bounds_values, list) or len(bounds_values) != 4:
            raise ValueError("document canvas_bounds must contain four values")
        policy_item = item.get("policy")
        if not isinstance(policy_item, dict):
            raise TypeError("document policy must be an object")
        return CompositionRecord(
            composition_id=uuid.UUID(str(item["composition_id"])),
            origin=CompositionOrigin.COMPOSITION,
            title=str(item["title"]),
            canvas_bounds=QRectF(*(float(value) for value in bounds_values)),
            policy=CompositionDocumentPolicy(
                removable=bool(policy_item["removable"]),
            ),
        )

    @staticmethod
    def _legacy_document(
        composition_id: uuid.UUID,
        _base_image_id: uuid.UUID,
        layers: tuple[CompositionLayerInstance, ...],
        masks: dict[uuid.UUID, CoverageAssetSnapshot],
        rasters: dict[uuid.UUID, SparseRasterSnapshot],
        vectors: dict[uuid.UUID, VectorDocument],
    ) -> CompositionRecord:
        """Migrate a pre-document archive into one explicit document value."""
        placements = []
        for layer in layers:
            bounds = None
            if (
                isinstance(layer.source, ProjectResourceReference)
                and layer.source.resource_id in masks
            ):
                snapshot = masks.get(layer.source.resource_id)
                bounds = None if snapshot is None else snapshot.raster.bounds
            elif isinstance(layer.source, ProjectResourceReference):
                snapshot = rasters.get(layer.source.resource_id)
                bounds = None if snapshot is None else snapshot.bounds
            elif (
                isinstance(layer.source, ProjectResourceReference)
                and layer.source.resource_id in vectors
            ):
                document = vectors.get(layer.source.resource_id)
                bounds = None if document is None else document.bounds
            if bounds is not None:
                placements.append(layer.transform.map_bounds(bounds))
        if placements:
            left = min(placement.x for placement in placements)
            top = min(placement.y for placement in placements)
            right = max(placement.x + placement.width for placement in placements)
            bottom = max(placement.y + placement.height for placement in placements)
            canvas = QRectF(left, top, max(1.0, right - left), max(1.0, bottom - top))
        else:
            canvas = QRectF(0.0, 0.0, 1.0, 1.0)
        return CompositionRecord(
            composition_id=composition_id,
            origin=CompositionOrigin.COMPOSITION,
            title="Migrated composition",
            canvas_bounds=canvas,
        )

    @staticmethod
    def _decode_vector(vector_id: uuid.UUID, item: object) -> VectorDocument:
        """Validate and reconstruct one semantic vector document payload."""
        if not isinstance(item, dict):
            raise TypeError("vector document entries must be objects")
        bounds_values = item.get("bounds")
        object_values = item.get("objects")
        if not isinstance(bounds_values, list) or len(bounds_values) != 4:
            raise ValueError("vector bounds must contain four integers")
        if not isinstance(object_values, list):
            raise TypeError("vector objects must be a list")
        if len(object_values) > _MAX_VECTOR_OBJECTS:
            raise ValueError("vector document exceeds archive object limit")
        objects: list[VectorObject] = []
        point_count = 0
        for value in object_values:
            vector_object, object_points = decode_vector_object(value)
            point_count += object_points
            if point_count > _MAX_VECTOR_POINTS:
                raise ValueError("vector document exceeds archive point limit")
            objects.append(vector_object)
        return VectorDocument(
            vector_id=vector_id,
            bounds=RasterBounds(*(int(value) for value in bounds_values)),
            objects=tuple(objects),
            revision=int(item.get("revision", 0)),
        )

    @staticmethod
    def _decode_placed(
        container: zipfile.ZipFile,
        asset_id: str,
        item: object,
    ) -> PlacedAssetSnapshot:
        """Validate and reconstruct one placed provenance payload."""
        if not isinstance(item, dict):
            raise TypeError("placed asset entries must be objects")
        size_values = item.get("source_size")
        if not isinstance(size_values, list) or len(size_values) != 2:
            raise ValueError("placed source_size must contain two integers")
        source_size = QSize(int(size_values[0]), int(size_values[1]))
        if source_size.isEmpty():
            raise ValueError("placed source_size must be positive")
        if source_size.width() * source_size.height() > _MAX_RASTER_PIXELS:
            raise ValueError("placed raster exceeds archive pixel limit")
        mode = PlacedAssetMode(str(item["mode"]))
        keep_fallback = bool(item["keep_fallback"])
        pixel_path = item.get("pixels")
        image = None
        if pixel_path is not None:
            expected_path = f"placed/{asset_id}.npy"
            if pixel_path != expected_path:
                raise ValueError("placed pixel path does not match its identifier")
            info = container.getinfo(expected_path)
            if info.file_size > _MAX_COLOR_RASTER_BYTES + 4096:
                raise ValueError("placed pixel payload exceeds archive size limit")
            with container.open(expected_path) as stream:
                pixels = np.load(stream, allow_pickle=False)
            image = numpy_to_qimage_argb32(pixels)
            if image.size() != source_size:
                raise ValueError("placed pixels do not match source_size")
        if mode is PlacedAssetMode.EMBEDDED and image is None:
            raise ValueError("embedded placed assets require archived pixels")
        source_path_value = item.get("source_path")
        source_path = (
            None if source_path_value is None else Path(str(source_path_value))
        )
        fingerprint_values = item.get("fingerprint")
        fingerprint = None
        if fingerprint_values is not None:
            if not isinstance(fingerprint_values, list) or len(fingerprint_values) != 2:
                raise ValueError(
                    "placed fingerprint must contain size and modified time"
                )
            fingerprint = FileFingerprint(
                int(fingerprint_values[0]),
                int(fingerprint_values[1]),
            )
        status = PlacedAssetStatus(str(item["status"]))
        error = None if item.get("error") is None else str(item["error"])
        if mode is PlacedAssetMode.LINKED and image is None:
            status = PlacedAssetStatus.MISSING
            error = "linked pixels were not embedded in the composition archive"
        return PlacedAssetSnapshot(
            image=image,
            source_size=source_size,
            mode=mode,
            source_path=source_path,
            status=status,
            error=error,
            keep_fallback=keep_fallback,
            fingerprint=fingerprint,
            content_revision=int(item["content_revision"]),
            generation=int(item["generation"]),
        )

    @staticmethod
    def _decode_mask(
        container: zipfile.ZipFile,
        mask_id: str,
        item: object,
        *,
        retained: bool = False,
        authored: bool = False,
    ) -> CoverageAssetSnapshot:
        """Validate and reconstruct one complete hybrid mask entry."""
        if not isinstance(item, dict):
            raise TypeError("mask entries must be objects")
        if item.get("storage") == "sparse-tiles":
            if item.get("bounds") is None:
                tiles = item.get("tiles")
                if tiles != []:
                    raise ValueError("null mask storage cannot contain sparse tiles")
                raster = SparseRasterSnapshot(
                    None,
                    RasterExtentPolicy(item["extent_policy"]),
                    1,
                    int(item["tile_size"]),
                    (),
                )
            else:
                raster = CompositionArchiveCodec._decode_sparse_tiles(
                    container,
                    "masks",
                    mask_id,
                    item,
                    channels=1,
                    byte_limit=_MAX_RASTER_PIXELS,
                )
        else:
            bounds_values = item["bounds"]
            if not isinstance(bounds_values, list) or len(bounds_values) != 4:
                raise ValueError("mask bounds must contain four integers")
            bounds = RasterBounds(*(int(value) for value in bounds_values))
            if bounds.width * bounds.height > _MAX_RASTER_PIXELS:
                raise ValueError("mask surface exceeds archive pixel limit")
            pixel_path = item["pixels"]
            expected_path = f"masks/{mask_id}.npy"
            if pixel_path != expected_path:
                raise ValueError("mask pixel path does not match its identifier")
            info = container.getinfo(expected_path)
            if info.file_size > _MAX_RASTER_PIXELS + 4096:
                raise ValueError("mask pixel payload exceeds archive size limit")
            with container.open(expected_path) as stream:
                pixels = np.load(stream, allow_pickle=False)
            snapshot = CoverageSnapshot(
                bounds=bounds,
                extent_policy=RasterExtentPolicy(item["extent_policy"]),
                pixels=pixels,
            )
            raster = _sparse_from_dense(
                snapshot.bounds,
                snapshot.extent_policy,
                snapshot.pixels,
                channels=1,
            )
        resource_id = uuid.UUID(mask_id)
        document = (
            decode_coverage_document(
                container,
                resource_id,
                item.get("retained"),
                pixel_limit=_MAX_RASTER_PIXELS,
            )
            if retained
            else CoverageDocument(document_id=resource_id)
        )
        authored_bounds = (
            _decode_optional_bounds(item.get("authored_bounds"))
            if authored
            else raster.bounds
        )
        return CoverageAssetSnapshot(raster, document, authored_bounds)

    @staticmethod
    def _decode_raster(
        container: zipfile.ZipFile,
        raster_id: str,
        item: object,
    ) -> SparseRasterSnapshot:
        """Validate and reconstruct one editable color raster payload."""
        if not isinstance(item, dict):
            raise TypeError("raster entries must be objects")
        if item.get("storage") == "sparse-tiles":
            return CompositionArchiveCodec._decode_sparse_tiles(
                container,
                "rasters",
                raster_id,
                item,
                channels=4,
                byte_limit=_MAX_COLOR_RASTER_BYTES,
            )
        bounds_values = item["bounds"]
        if not isinstance(bounds_values, list) or len(bounds_values) != 4:
            raise ValueError("raster bounds must contain four integers")
        bounds = RasterBounds(*(int(value) for value in bounds_values))
        if bounds.width * bounds.height > _MAX_RASTER_PIXELS:
            raise ValueError("color raster exceeds archive pixel limit")
        expected_path = f"rasters/{raster_id}.npy"
        if item["pixels"] != expected_path:
            raise ValueError("raster pixel path does not match its identifier")
        info = container.getinfo(expected_path)
        if info.file_size > _MAX_COLOR_RASTER_BYTES + 4096:
            raise ValueError("color raster payload exceeds archive size limit")
        with container.open(expected_path) as stream:
            pixels = np.load(stream, allow_pickle=False)
        snapshot = ColorRasterSnapshot(
            bounds=bounds,
            extent_policy=RasterExtentPolicy(item["extent_policy"]),
            pixels=pixels,
        )
        return _sparse_from_dense(
            snapshot.bounds,
            snapshot.extent_policy,
            snapshot.pixels,
            channels=4,
        )

    @staticmethod
    def _decode_sparse_tiles(
        container: zipfile.ZipFile,
        domain: str,
        resource_id: str,
        item: dict[str, object],
        *,
        channels: int,
        byte_limit: int,
    ) -> SparseRasterSnapshot:
        """Validate and reconstruct allocated tiles without reading their envelope."""
        bounds_values = item.get("bounds")
        if not isinstance(bounds_values, list) or len(bounds_values) != 4:
            raise ValueError("sparse raster bounds must contain four integers")
        bounds = RasterBounds(*(int(value) for value in bounds_values))
        tile_size = int(item.get("tile_size", 0))
        if tile_size < 16 or tile_size > 4096:
            raise ValueError("sparse raster tile_size is invalid")
        if int(item.get("channels", 0)) != channels:
            raise ValueError("sparse raster channel count is invalid")
        tile_items = item.get("tiles")
        if not isinstance(tile_items, list):
            raise TypeError("sparse raster tiles must be a list")
        maximum_tiles = max(1, byte_limit // (tile_size * tile_size * channels))
        if len(tile_items) > maximum_tiles:
            raise ValueError("sparse raster exceeds archive tile limit")
        tiles: list[SparseRasterTile] = []
        retained_bytes = 0
        observed_bounds: set[RasterBounds] = set()
        for index, tile_item in enumerate(tile_items):
            if not isinstance(tile_item, dict):
                raise TypeError("sparse raster tile entries must be objects")
            tile_bounds_values = tile_item.get("bounds")
            if not isinstance(tile_bounds_values, list) or len(tile_bounds_values) != 4:
                raise ValueError("sparse tile bounds must contain four integers")
            tile_bounds = RasterBounds(*(int(value) for value in tile_bounds_values))
            if (
                tile_bounds.width != tile_size
                or tile_bounds.height != tile_size
                or tile_bounds.x % tile_size
                or tile_bounds.y % tile_size
                or tile_bounds in observed_bounds
            ):
                raise ValueError("sparse tile geometry is invalid or duplicated")
            expected_path = f"{domain}/{resource_id}/{index}.npy"
            if tile_item.get("pixels") != expected_path:
                raise ValueError("sparse tile path does not match its index")
            info = container.getinfo(expected_path)
            retained_bytes += info.file_size
            if retained_bytes > byte_limit + len(tile_items) * 4096:
                raise ValueError("sparse raster payload exceeds archive size limit")
            with container.open(expected_path) as stream:
                pixels = np.load(stream, allow_pickle=False)
            tiles.append(SparseRasterTile(tile_bounds, pixels))
            observed_bounds.add(tile_bounds)
        return SparseRasterSnapshot(
            bounds,
            RasterExtentPolicy(str(item["extent_policy"])),
            channels,
            tile_size,
            tuple(tiles),
        )

    @staticmethod
    def _validate_header(manifest: object) -> int:
        """Reject unknown formats, versions, or malformed root collections."""
        if not isinstance(manifest, dict):
            raise TypeError("archive manifest must be an object")
        if manifest.get("format") != _FORMAT:
            raise ValueError("unsupported composition archive format")
        version = manifest.get("version")
        if version not in _MIGRATABLE_VERSIONS:
            raise ValueError("unsupported composition archive version")
        if version == 2:
            if not isinstance(manifest.get("layers"), list):
                raise TypeError("archive layers must be a list")
            if not isinstance(manifest.get("masks"), dict):
                raise TypeError("archive masks must be an object")
            if not isinstance(manifest.get("rasters", {}), dict):
                raise TypeError("archive rasters must be an object")
        else:
            if not isinstance(manifest.get("resources"), list):
                raise TypeError("archive resources must be a list")
            if version >= 11:
                if not isinstance(manifest.get("documents"), list):
                    raise TypeError("archive documents must be a list")
                if not isinstance(manifest.get("root_document_id"), str):
                    raise TypeError("archive root_document_id must be a string")
                if "root_document_ids" in manifest and not isinstance(
                    manifest["root_document_ids"], list
                ):
                    raise TypeError("archive root_document_ids must be a list")
            elif not isinstance(manifest.get("instances"), list):
                raise TypeError("archive instances must be a list")
            if 8 <= version < 11 and not isinstance(manifest.get("document"), dict):
                raise TypeError("archive document must be an object")
        return int(version)

    @staticmethod
    def _validate_references(archive: CompositionArchiveSnapshot) -> None:
        """Require one base image and exact mask payload references."""
        mask_ids = {
            resource_id
            for resource_id, resource in archive.resources.items()
            if resource.kind is ProjectResourceKind.COVERAGE
        }
        if mask_ids != set(archive.masks):
            raise ValueError("archive mask sources and payloads must match")
        raster_ids = {
            resource_id
            for resource_id, resource in archive.resources.items()
            if resource.kind is ProjectResourceKind.RASTER
        }
        if raster_ids != set(archive.rasters):
            raise ValueError("archive raster sources and payloads must match")
        placed_ids = {
            resource_id
            for resource_id, resource in archive.resources.items()
            if resource.kind
            in {
                ProjectResourceKind.IMPORTED_RASTER,
                ProjectResourceKind.LINKED_RASTER,
            }
        }
        if placed_ids != set(archive.placed_assets):
            raise ValueError("archive placed sources and payloads must match")
        vector_ids = {
            resource_id
            for resource_id, resource in archive.resources.items()
            if resource.kind is ProjectResourceKind.VECTOR
        }
        if vector_ids != set(archive.vectors):
            raise ValueError("archive vector sources and payloads must match")
        referenced_project_ids = {
            source.resource_id
            for layers in archive.layer_stacks.values()
            for layer in layers
            for source in instance_resources(layer)
            if isinstance(source, ProjectResourceReference)
        }
        if not referenced_project_ids.issubset(archive.resources):
            raise ValueError("archive project-resource sources require records")
        composition_ids = {
            resource_id
            for resource_id, resource in archive.resources.items()
            if resource.kind is ProjectResourceKind.COMPOSITION
        }
        if composition_ids != set(archive.documents):
            raise ValueError("archive composition resources and documents must match")


def _project_resource_manifest(
    record: ProjectResourceRecord,
) -> dict[str, object]:
    """Return one authoritative project-resource record manifest."""
    return {
        "kind": record.kind.value,
        "resource_id": str(record.resource_id),
        "editable": record.editable,
        "revision": record.revision,
        "dependencies": [
            str(resource_id) for resource_id in sorted(record.dependencies, key=str)
        ],
    }


def _decode_project_resource(
    item: dict[str, object],
    resource_id: uuid.UUID,
    kind: ProjectResourceKind,
    *,
    editable: bool,
    current: bool,
) -> ProjectResourceRecord:
    """Decode one current record or synthesize legacy resource metadata."""
    if not current:
        return ProjectResourceRecord(resource_id, kind, editable)
    dependencies = item.get("dependencies", [])
    if not isinstance(dependencies, list):
        raise TypeError("project resource dependencies must be a list")
    return ProjectResourceRecord(
        resource_id,
        kind,
        bool(item.get("editable", editable)),
        revision=int(item.get("revision", 0)),
        dependencies=frozenset(uuid.UUID(str(value)) for value in dependencies),
    )


def _validate_resource_table_references(
    layers: tuple[CompositionLayerInstance, ...],
    resource_keys: set[tuple[str, uuid.UUID]],
    project_resources: dict[uuid.UUID, ProjectResourceRecord],
) -> None:
    """Require every instance source while allowing dependency-only resources."""
    expected_non_project = {
        (source.kind, source.resource_id)
        for layer in layers
        for source in instance_resources(layer)
        if not isinstance(source, ProjectResourceReference)
    }
    actual_non_project = {
        key
        for key in resource_keys
        if key[0]
        not in {
            ProjectResourceKind.RASTER.value,
            ProjectResourceKind.IMPORTED_RASTER.value,
            ProjectResourceKind.LINKED_RASTER.value,
            ProjectResourceKind.COVERAGE.value,
            ProjectResourceKind.COMPOSITION.value,
            ProjectResourceKind.VECTOR.value,
            "placed-asset",
        }
    }
    if expected_non_project != actual_non_project:
        raise ValueError("archive instances and resource table must match")
    referenced_project = {
        source.resource_id
        for layer in layers
        for source in instance_resources(layer)
        if isinstance(source, ProjectResourceReference)
    }
    if not referenced_project.issubset(project_resources):
        raise ValueError("archive project-resource instances must have records")


def _coverage_manifest(
    mask_id: uuid.UUID, snapshot: CoverageAssetSnapshot
) -> dict[str, object]:
    """Return one mask resource payload manifest."""
    raster = snapshot.raster
    return {
        "bounds": _encode_optional_bounds(raster.bounds),
        "authored_bounds": _encode_optional_bounds(snapshot.authored_bounds),
        "extent_policy": raster.extent_policy.value,
        "storage": "sparse-tiles",
        "channels": raster.channels,
        "tile_size": raster.tile_size,
        "tiles": [
            {
                "bounds": [
                    tile.bounds.x,
                    tile.bounds.y,
                    tile.bounds.width,
                    tile.bounds.height,
                ],
                "pixels": f"masks/{mask_id}/{index}.npy",
            }
            for index, tile in enumerate(raster.tiles)
        ],
        "retained": encode_coverage_document(mask_id, snapshot.retained),
    }


def _encode_optional_bounds(bounds: RasterBounds | None) -> list[int] | None:
    """Encode nullable raster geometry without inventing transparent storage."""
    return None if bounds is None else [bounds.x, bounds.y, bounds.width, bounds.height]


def _decode_optional_bounds(value: object) -> RasterBounds | None:
    """Decode nullable raster geometry from a validated four-integer sequence."""
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError("optional raster bounds must contain four integers")
    return RasterBounds(*(int(component) for component in value))


def _raster_manifest(
    raster_id: uuid.UUID, snapshot: SparseRasterSnapshot
) -> dict[str, object]:
    """Return one editable-raster resource payload manifest."""
    return {
        "bounds": [
            snapshot.bounds.x,
            snapshot.bounds.y,
            snapshot.bounds.width,
            snapshot.bounds.height,
        ],
        "extent_policy": snapshot.extent_policy.value,
        "storage": "sparse-tiles",
        "channels": snapshot.channels,
        "tile_size": snapshot.tile_size,
        "tiles": [
            {
                "bounds": [
                    tile.bounds.x,
                    tile.bounds.y,
                    tile.bounds.width,
                    tile.bounds.height,
                ],
                "pixels": f"rasters/{raster_id}/{index}.npy",
            }
            for index, tile in enumerate(snapshot.tiles)
        ],
    }


def _sparse_from_dense(
    bounds: RasterBounds | None,
    extent_policy: RasterExtentPolicy,
    pixels: np.ndarray,
    *,
    channels: int,
) -> SparseRasterSnapshot:
    """Migrate one legacy dense payload into current sparse authority."""
    grid = SparseRasterGrid(channels=channels, tile_size=512)
    if bounds is not None:
        grid.replace(bounds, pixels)
    return grid.snapshot(bounds, extent_policy)


def _placed_manifest(
    asset_id: uuid.UUID,
    snapshot: PlacedAssetSnapshot,
) -> dict[str, object]:
    """Return provenance and optional fallback metadata for a placed source."""
    include_pixels = snapshot.image is not None and (
        snapshot.mode is PlacedAssetMode.EMBEDDED or snapshot.keep_fallback
    )
    fingerprint = (
        None
        if snapshot.fingerprint is None
        else [snapshot.fingerprint.size, snapshot.fingerprint.modified_ns]
    )
    return {
        "mode": snapshot.mode.value,
        "source_path": (
            None if snapshot.source_path is None else str(snapshot.source_path)
        ),
        "status": snapshot.status.value,
        "error": snapshot.error,
        "keep_fallback": snapshot.keep_fallback,
        "fingerprint": fingerprint,
        "content_revision": snapshot.content_revision,
        "generation": snapshot.generation,
        "source_size": [
            snapshot.source_size.width(),
            snapshot.source_size.height(),
        ],
        "pixels": f"placed/{asset_id}.npy" if include_pixels else None,
    }


def _vector_manifest(document: VectorDocument) -> dict[str, object]:
    """Return serializable semantic geometry for one vector document."""
    return {
        "bounds": [
            document.bounds.x,
            document.bounds.y,
            document.bounds.width,
            document.bounds.height,
        ],
        "revision": document.revision,
        "objects": [encode_vector_object(item) for item in document.objects],
    }
