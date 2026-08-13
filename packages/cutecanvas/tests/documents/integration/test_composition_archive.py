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
"""Private durable composition archive round-trip and validation tests."""

from __future__ import annotations

import json
import uuid
import zipfile
from dataclasses import dataclass, replace

import numpy as np
import pytest
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QImage

from cutecanvas import (
    RasterExtentPolicy,
    VectorFillRule,
    VectorParagraphStyle,
    VectorPathCommand,
    VectorPathCommandKind,
    VectorStyle,
    VectorTextAlignment,
    VectorTextContent,
    VectorTextDirection,
    VectorTextSpan,
    VectorTextStyle,
)
from cutecanvas.composition.layers import (
    CompositionLayerInstance,
    CompositionLayerStore,
)
from cutecanvas.composition.model import (
    CompositionDocumentPolicy,
    CompositionOrigin,
    CompositionRecord,
)
from cutecanvas.composition.resource_lifetime import CompositionResourceLifetime
from cutecanvas.composition.service import CompositionService
from cutecanvas.coverage import (
    CoverageCombineMode,
    CoverageGeometryFactory,
    CoverageSnapshot,
    RasterCoverageItem,
    StrokeCoverageItem,
    VectorCoverageItem,
)
from cutecanvas.masks.mask import MaskAssetStore
from cutecanvas.painting import BrushStrokeSegment
from cutecanvas.persistence import (
    CompositionArchiveCodec,
    CompositionArchiveRestorer,
    capture_composition,
)
from cutecanvas.placed.model import FileFingerprint, PlacedAssetStatus
from cutecanvas.placed.store import PlacedAssetStore
from cutecanvas.raster.assets import EditableRasterAssetStore
from cutecanvas.resources import ProjectResourceReference, ProjectResourceStore
from cutecanvas.resources.composition_resources import CompositionResourceOwner
from cutecanvas.vector.effects import VectorMaskEffect
from cutecanvas.vector.store import VectorAssetStore
from qpane.scene.affine import LayerTransform
from qpane.scene.model import LayerInteractionPolicy, LayerPlacement
from qpane.scene.projective import ProjectiveLayerTransform
from qpane.scene.raster import RasterBounds
from qpane.vector.model import VectorObject
from qpane.vector.public import VectorObjectKind


class _FailingOnceLayerStore(CompositionLayerStore):
    """Inject one post-mutation layer replacement failure for rollback proof."""

    def __init__(self, lifetime: CompositionResourceLifetime) -> None:
        """Initialize the store with failure injection disarmed."""
        super().__init__(lifetime)
        self.fail_next_replacement = False

    def replace_layers(
        self,
        composition_id: uuid.UUID,
        instances: tuple[CompositionLayerInstance, ...],
    ) -> None:
        """Mutate normally, then fail once so restoration must undo every owner."""
        super().replace_layers(composition_id, instances)
        if self.fail_next_replacement:
            self.fail_next_replacement = False
            raise RuntimeError("injected layer publication failure")


@dataclass(frozen=True, slots=True)
class _ArchiveOwners:
    """Group payload owners sharing one authoritative project-resource graph."""

    resources: ProjectResourceStore
    masks: MaskAssetStore
    rasters: EditableRasterAssetStore
    placed_assets: PlacedAssetStore
    vectors: VectorAssetStore


def _resource_owners() -> _ArchiveOwners:
    """Return every persistence owner over one authoritative resource graph."""
    resources = ProjectResourceStore()
    return _ArchiveOwners(
        resources=resources,
        masks=MaskAssetStore(resources),
        rasters=EditableRasterAssetStore(resources),
        placed_assets=PlacedAssetStore(resources),
        vectors=VectorAssetStore(resources),
    )


def _ensure_default(
    layers: CompositionLayerStore,
    placed_assets: PlacedAssetStore,
    composition_id: uuid.UUID,
    image_id: uuid.UUID,
    width: int,
    height: int,
) -> None:
    """Create one generated composition stack for archive tests."""
    bounds = RasterBounds(0, 0, width, height)
    placement = LayerPlacement(0.0, 0.0, float(width), float(height))
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor(30, 60, 90, 255))
    resource_id = (
        uuid.uuid5(composition_id, "archive-base")
        if image_id == composition_id
        else image_id
    )
    placed_assets.create_embedded(image, asset_id=resource_id)
    layers.ensure_composition(
        composition_id,
        (
            CompositionLayerInstance(
                layer_id=uuid.uuid5(resource_id, "archive-layer"),
                source=ProjectResourceReference(resource_id),
                transform=LayerTransform.from_placement(bounds, placement),
                role="base-image",
            ),
        ),
    )


def _document(
    composition_id: uuid.UUID,
    width: int = 1,
    height: int = 1,
) -> CompositionRecord:
    """Return one independent document value for archive tests."""
    return CompositionRecord(
        composition_id=composition_id,
        origin=CompositionOrigin.COMPOSITION,
        title="Archive",
        canvas_bounds=QRectF(0.0, 0.0, float(width), float(height)),
    )


def _composition_owner(
    layers: CompositionLayerStore,
    document: CompositionRecord,
    resources: ProjectResourceStore,
) -> CompositionService:
    """Bind a characterized layer store to its document owner for restoration."""
    document_resources = CompositionResourceOwner(resources)
    service = CompositionService(document_resources=document_resources)
    service._layers = layers
    service._records[document.composition_id] = document
    service._order.append(document.composition_id)
    service._active_id = document.composition_id
    document_resources.synchronize(
        document.composition_id,
        layers.layers_for_composition(document.composition_id),
    )
    return service


def test_empty_document_round_trips_canvas_policy_and_empty_stack(tmp_path) -> None:
    """Persistence must not invent an image or layer for an empty document."""
    composition_id = uuid.uuid4()
    document = CompositionRecord(
        composition_id=composition_id,
        origin=CompositionOrigin.COMPOSITION,
        title="Empty durable document",
        canvas_bounds=QRectF(-32.0, 18.0, 4096.0, 2160.0),
        policy=CompositionDocumentPolicy(
            removable=False,
        ),
    )
    layers = CompositionLayerStore(CompositionResourceLifetime())
    layers.ensure_composition(composition_id, ())
    owners = _resource_owners()
    compositions = _composition_owner(layers, document, owners.resources)
    archive = capture_composition(
        composition_id,
        compositions,
        owners.masks,
        owners.rasters,
        owners.placed_assets,
        owners.vectors,
    )
    path = tmp_path / "empty.qpane"
    codec = CompositionArchiveCodec()

    codec.write(archive, path)
    decoded = codec.read(path)

    assert decoded.documents[composition_id] == document
    assert decoded.layer_stacks[composition_id] == ()
    restored_owners = _resource_owners()
    restored = CompositionService(
        document_resources=CompositionResourceOwner(restored_owners.resources)
    )
    CompositionArchiveRestorer(
        compositions=restored,
        masks=restored_owners.masks,
        rasters=restored_owners.rasters,
        placed_assets=restored_owners.placed_assets,
        vectors=restored_owners.vectors,
    ).restore(decoded)
    assert restored.record(composition_id) == document
    assert restored.layers.layers_for_composition(composition_id) == ()


def test_private_archive_round_trip_restores_order_transform_and_off_canvas_pixels(
    tmp_path,
) -> None:
    """Every durable authoring value should survive a private archive round trip."""
    image_id = uuid.uuid4()
    owners = _resource_owners()
    layers = CompositionLayerStore(CompositionResourceLifetime())
    _ensure_default(layers, owners.placed_assets, image_id, image_id, 8, 6)
    masks = owners.masks
    rasters = owners.rasters
    placed_assets = owners.placed_assets
    mask_id = masks.create_mask(QImage(8, 6, QImage.Format_Grayscale8))
    mask = masks.get_layer(mask_id)
    assert mask is not None
    expanded_bounds = RasterBounds(-3, -2, 13, 10)
    mask.coverage.raster.set_extent_policy(RasterExtentPolicy.EXPAND_ON_WRITE)
    mask.coverage.raster.set_bounds(expanded_bounds)
    mask.coverage.raster.mutate(lambda pixels, _image: pixels.__setitem__((1, 1), 217))
    mask_instance = CompositionLayerInstance(
        layer_id=uuid.uuid4(),
        source=ProjectResourceReference(mask_id),
        transform=ProjectiveLayerTransform(
            m11=1.0,
            m13=0.001,
            m22=1.0,
            dx=12.0,
            dy=-4.0,
        ),
        opacity=0.35,
        tint=QColor(12, 34, 56, 200),
        interaction=LayerInteractionPolicy(selectable=True, movable=True),
        role="mask",
        label="Off canvas",
    )
    assert layers.add_layer(image_id, mask_instance)
    assert layers.reorder_layer(image_id, mask_instance.layer_id, 0)
    raster_image = QImage(4, 3, QImage.Format_ARGB32_Premultiplied)
    raster_image.fill(QColor(90, 30, 170, 211))
    raster = rasters.create(
        raster_image,
        bounds=RasterBounds(-5, 7, 4, 3),
        extent_policy=RasterExtentPolicy.EXPAND_ON_WRITE,
    )
    expected_raster_pixels = raster.surface.snapshot().pixels
    raster_instance = CompositionLayerInstance(
        layer_id=uuid.uuid4(),
        source=ProjectResourceReference(raster.raster_id),
        transform=LayerTransform(
            m11=-0.75,
            m12=0.2,
            m21=0.35,
            m22=1.25,
            dx=-8.0,
            dy=4.0,
        ),
        interaction=LayerInteractionPolicy(
            selectable=True,
            movable=True,
            pixel_editable=True,
        ),
        role="raster",
        label="Paint",
    )
    assert layers.add_layer(image_id, raster_instance)
    assert (
        layers.duplicate_layer(
            image_id,
            raster_instance.layer_id,
            uuid.uuid4(),
            transform=LayerTransform(
                m11=-0.75,
                m12=0.2,
                m21=0.35,
                m22=1.25,
                dx=20.0,
                dy=4.0,
            ),
        )
        is not None
    )
    archive_path = tmp_path / "composition.qpc"
    codec = CompositionArchiveCodec()

    codec.write(
        capture_composition(
            image_id,
            _composition_owner(
                layers,
                _document(image_id, 8, 6),
                owners.resources,
            ),
            masks,
            rasters,
            placed_assets,
            owners.vectors,
        ),
        archive_path,
    )
    with zipfile.ZipFile(archive_path) as container:
        manifest = json.loads(container.read("manifest.json"))
    assert manifest["version"] == 15
    assert manifest["documents"][0]["document"]["canvas_bounds"] == [
        0.0,
        0.0,
        8.0,
        6.0,
    ]
    assert len(manifest["documents"][0]["instances"]) == 4
    assert len(manifest["resources"]) == 4
    assert sorted(
        len(instance["transform"]) for instance in manifest["documents"][0]["instances"]
    ) == [6, 6, 6, 9]
    decoded = codec.read(archive_path)
    restored_owners = _resource_owners()
    restored_layers = CompositionLayerStore(CompositionResourceLifetime())
    _ensure_default(
        restored_layers,
        restored_owners.placed_assets,
        image_id,
        image_id,
        8,
        6,
    )
    CompositionArchiveRestorer(
        compositions=_composition_owner(
            restored_layers,
            _document(image_id, 8, 6),
            restored_owners.resources,
        ),
        masks=restored_owners.masks,
        rasters=restored_owners.rasters,
        placed_assets=restored_owners.placed_assets,
        vectors=restored_owners.vectors,
    ).restore(decoded)

    assert restored_layers.layers_for_composition(
        image_id
    ) == layers.layers_for_composition(image_id)
    restored_mask = restored_owners.masks.get_layer(mask_id)
    assert restored_mask is not None
    restored = restored_mask.coverage.raster.snapshot()
    assert restored.bounds == RasterBounds(-2, -1, 1, 1)
    assert restored.extent_policy is RasterExtentPolicy.EXPAND_ON_WRITE
    assert restored.pixels[0, 0] == 217
    assert restored.pixels.shape == (1, 1)
    assert restored_mask.coverage.authored_bounds == RasterBounds(0, 0, 8, 6)
    restored_raster = restored_owners.rasters.get(raster.raster_id)
    assert restored_raster is not None
    raster_snapshot = restored_raster.surface.snapshot()
    assert raster_snapshot.bounds == RasterBounds(-5, 7, 4, 3)
    assert raster_snapshot.extent_policy is RasterExtentPolicy.EXPAND_ON_WRITE
    assert np.array_equal(raster_snapshot.pixels, expected_raster_pixels)


def test_archive_preserves_authored_mask_extent_without_transparent_storage(
    tmp_path,
) -> None:
    """A compact empty mask must remain authored and editable after restoration."""
    composition_id = uuid.uuid4()
    owners = _resource_owners()
    layers = CompositionLayerStore(CompositionResourceLifetime())
    _ensure_default(
        layers,
        owners.placed_assets,
        composition_id,
        composition_id,
        8,
        6,
    )
    blank = QImage(8, 6, QImage.Format_Grayscale8)
    blank.fill(0)
    mask_id = owners.masks.create_mask(blank)
    mask = owners.masks.get_layer(mask_id)
    assert mask is not None
    assert mask.coverage.compact_raster_storage()
    assert layers.add_layer(
        composition_id,
        CompositionLayerInstance(
            layer_id=uuid.uuid4(),
            source=ProjectResourceReference(mask_id),
            interaction=LayerInteractionPolicy(
                selectable=True,
                movable=True,
                pixel_editable=True,
            ),
            role="mask",
        ),
    )
    path = tmp_path / "empty-authored-mask.qpc"
    codec = CompositionArchiveCodec()
    codec.write(
        capture_composition(
            composition_id,
            _composition_owner(
                layers,
                _document(composition_id, 8, 6),
                owners.resources,
            ),
            owners.masks,
            owners.rasters,
            owners.placed_assets,
            owners.vectors,
        ),
        path,
    )

    restored = codec.read(path).masks[mask_id]

    assert restored.raster.bounds is None
    assert restored.raster.tiles == ()
    assert restored.authored_bounds == RasterBounds(0, 0, 8, 6)


def test_archive_round_trip_preserves_hybrid_mask_authorship(tmp_path) -> None:
    """Raster, vector, and procedural mask items remain editable after restore."""
    composition_id = uuid.uuid4()
    owners = _resource_owners()
    layers = CompositionLayerStore(CompositionResourceLifetime())
    _ensure_default(
        layers,
        owners.placed_assets,
        composition_id,
        composition_id,
        64,
        48,
    )
    masks = owners.masks
    mask_id = masks.create_mask(QImage(64, 48, QImage.Format_Grayscale8))
    mask = masks.get_layer(mask_id)
    assert mask is not None
    raster_pixels = np.full((4, 5), 171, dtype=np.uint8)
    raster_item = RasterCoverageItem(
        uuid.uuid4(),
        CoverageSnapshot(
            RasterBounds(3, 4, 5, 4),
            RasterExtentPolicy.EXPAND_ON_WRITE,
            raster_pixels,
        ),
        CoverageCombineMode.ADD,
        LayerTransform(dx=2.0, dy=-1.0),
    )
    vector_item = VectorCoverageItem(
        uuid.uuid4(),
        CoverageGeometryFactory().ellipse(QRectF(16.0, 8.0, 12.0, 10.0)),
        CoverageCombineMode.SUBTRACT,
        LayerTransform(m11=1.5, m22=0.75, dx=-3.0, dy=2.0),
        2.5,
    )
    stroke_item = StrokeCoverageItem(
        uuid.uuid4(),
        (BrushStrokeSegment.fixed((1.0, 2.0), (20.0, 15.0), 7.0, False),),
        CoverageCombineMode.ADD,
        LayerTransform(dx=4.0, dy=3.0),
    )
    for item in (raster_item, vector_item, stroke_item):
        assert mask.coverage.append(item)
    assert layers.add_layer(
        composition_id,
        CompositionLayerInstance(
            layer_id=uuid.uuid4(),
            source=ProjectResourceReference(mask_id),
            interaction=LayerInteractionPolicy(
                selectable=True,
                movable=True,
                pixel_editable=True,
            ),
        ),
    )
    expected = mask.coverage.snapshot()
    path = tmp_path / "hybrid-mask.qpc"
    codec = CompositionArchiveCodec()
    codec.write(
        capture_composition(
            composition_id,
            _composition_owner(
                layers,
                _document(composition_id, 64, 48),
                owners.resources,
            ),
            masks,
            owners.rasters,
            owners.placed_assets,
            owners.vectors,
        ),
        path,
    )

    decoded = codec.read(path)
    retained = decoded.masks[mask_id].retained
    assert tuple(type(item) for item in retained.items) == (
        RasterCoverageItem,
        VectorCoverageItem,
        StrokeCoverageItem,
    )
    decoded_raster = retained.items[0]
    assert isinstance(decoded_raster, RasterCoverageItem)
    np.testing.assert_array_equal(decoded_raster.coverage.pixels, raster_pixels)
    restored = MaskAssetStore(ProjectResourceStore())
    restored.restore_mask(mask_id, decoded.masks[mask_id])
    restored_layer = restored.get_layer(mask_id)
    assert restored_layer is not None
    actual = restored_layer.coverage.snapshot()
    assert actual.bounds == expected.bounds
    np.testing.assert_array_equal(actual.pixels, expected.pixels)


def test_archive_keeps_million_coordinate_rasters_sparse_and_durable(tmp_path) -> None:
    """Far-apart off-canvas pixels must round-trip without encoding their gap."""
    image_id = uuid.uuid4()
    owners = _resource_owners()
    layers = CompositionLayerStore(CompositionResourceLifetime())
    _ensure_default(layers, owners.placed_assets, image_id, image_id, 64, 48)
    masks = owners.masks
    rasters = owners.rasters
    negative = RasterBounds(-1_000_000, -1_000_000, 8, 8)
    positive = RasterBounds(1_000_000, 1_000_000, 8, 8)

    mask_seed = QImage(1, 1, QImage.Format_Grayscale8)
    mask_seed.fill(0)
    mask_id = masks.create_mask(mask_seed)
    mask = masks.get_layer(mask_id)
    assert mask is not None
    assert mask.coverage.raster.set_extent_policy(RasterExtentPolicy.UNBOUNDED)
    for bounds, value in ((negative, 83), (positive, 197)):
        writable = mask.coverage.raster.ensure_writable(bounds)
        assert writable.writable == bounds
        storage = mask.coverage.raster.storage_rect(bounds)
        assert storage is not None
        mask.coverage.raster.mutate_storage_region(
            storage,
            lambda pixels, _image, fill=value: pixels.fill(fill),
        )
    assert mask.coverage.raster.allocated_bytes <= 2 * 512 * 512
    assert layers.add_layer(
        image_id,
        CompositionLayerInstance(
            layer_id=uuid.uuid4(),
            source=ProjectResourceReference(mask_id),
            transform=LayerTransform(),
            interaction=LayerInteractionPolicy(
                selectable=True,
                movable=True,
                pixel_editable=True,
            ),
        ),
    )

    raster_seed = QImage(1, 1, QImage.Format_ARGB32_Premultiplied)
    raster_seed.fill(0)
    raster = rasters.create(
        raster_seed,
        extent_policy=RasterExtentPolicy.UNBOUNDED,
    )
    for bounds, value in ((negative, 111), (positive, 223)):
        assert raster.surface.ensure_bounds(bounds)

        def fill_rgba(pixels, channel=value) -> bool:
            """Fill one sparse patch with opaque premultiplied pixels."""
            pixels.fill(channel)
            pixels[:, :, 3] = 255
            return True

        assert raster.surface.mutate_patch(bounds, fill_rgba)
    assert raster.surface.allocated_bytes <= 2 * 512 * 512 * 4
    assert layers.add_layer(
        image_id,
        CompositionLayerInstance(
            layer_id=uuid.uuid4(),
            source=ProjectResourceReference(raster.raster_id),
            transform=LayerTransform(),
            interaction=LayerInteractionPolicy(
                selectable=True,
                movable=True,
                pixel_editable=True,
            ),
        ),
    )

    archive_path = tmp_path / "sparse-million-coordinate.qpc"
    codec = CompositionArchiveCodec()
    codec.write(
        capture_composition(
            image_id,
            _composition_owner(
                layers,
                _document(image_id, 64, 48),
                owners.resources,
            ),
            masks,
            rasters,
            owners.placed_assets,
            owners.vectors,
        ),
        archive_path,
    )
    assert archive_path.stat().st_size < 8 * 1024 * 1024
    decoded = codec.read(archive_path)
    assert decoded.masks[mask_id].raster.retained_bytes <= 2 * 512 * 512
    assert decoded.rasters[raster.raster_id].retained_bytes <= 2 * 512 * 512 * 4

    restored_owners = _resource_owners()
    restored_layers = CompositionLayerStore(CompositionResourceLifetime())
    _ensure_default(
        restored_layers,
        restored_owners.placed_assets,
        image_id,
        image_id,
        64,
        48,
    )
    CompositionArchiveRestorer(
        compositions=_composition_owner(
            restored_layers,
            _document(image_id, 64, 48),
            restored_owners.resources,
        ),
        masks=restored_owners.masks,
        rasters=restored_owners.rasters,
        placed_assets=restored_owners.placed_assets,
        vectors=restored_owners.vectors,
    ).restore(decoded)
    restored_mask = restored_owners.masks.get_layer(mask_id)
    restored_raster = restored_owners.rasters.get(raster.raster_id)
    assert restored_mask is not None
    assert restored_raster is not None
    assert np.all(restored_mask.coverage.raster.capture_region(negative) == 83)
    assert np.all(restored_mask.coverage.raster.capture_region(positive) == 197)
    assert np.all(restored_raster.surface.capture_region(negative)[:, :, 0] == 111)
    assert np.all(restored_raster.surface.capture_region(positive)[:, :, 0] == 223)


def test_archive_rejects_unknown_version_before_restoration(tmp_path) -> None:
    """Readers should reject future formats without returning partial state."""
    path = tmp_path / "future.qpc"
    manifest = {
        "format": "qpane-composition",
        "version": 999,
        "image_id": str(uuid.uuid4()),
        "layers": [],
        "masks": {},
    }
    with zipfile.ZipFile(path, "w") as container:
        container.writestr("manifest.json", json.dumps(manifest))

    with pytest.raises(ValueError, match="version"):
        CompositionArchiveCodec().read(path)


def test_archive_write_replaces_destination_without_leaving_temp_files(
    tmp_path,
) -> None:
    """Successful writes should atomically replace an existing archive path."""
    image_id = uuid.uuid4()
    owners = _resource_owners()
    layers = CompositionLayerStore(CompositionResourceLifetime())
    _ensure_default(layers, owners.placed_assets, image_id, image_id, 2, 2)
    path = tmp_path / "composition.qpc"
    path.write_bytes(b"old")

    CompositionArchiveCodec().write(
        capture_composition(
            image_id,
            _composition_owner(
                layers,
                _document(image_id, 2, 2),
                owners.resources,
            ),
            owners.masks,
            owners.rasters,
            owners.placed_assets,
            owners.vectors,
        ),
        path,
    )

    assert zipfile.is_zipfile(path)
    assert not tuple(tmp_path.glob(".composition.qpc.*.tmp"))


def test_placed_sources_round_trip_fallback_policy_and_shared_instances(
    tmp_path,
) -> None:
    """Archives must deduplicate placed sources and honor offline fallback policy."""
    image_id = uuid.uuid4()
    owners = _resource_owners()
    layers = CompositionLayerStore(CompositionResourceLifetime())
    _ensure_default(layers, owners.placed_assets, image_id, image_id, 16, 12)
    placed_assets = owners.placed_assets
    fallback_image = QImage(6, 5, QImage.Format_ARGB32_Premultiplied)
    fallback_image.fill(QColor(21, 90, 180, 177))
    fallback_id = placed_assets.create_linked(
        fallback_image,
        tmp_path / "offline-fallback.png",
        FileFingerprint(123, 456),
        keep_fallback=True,
    )
    no_fallback_id = placed_assets.create_linked(
        fallback_image,
        tmp_path / "offline-link.png",
        FileFingerprint(789, 1011),
        keep_fallback=False,
    )
    first = CompositionLayerInstance(
        uuid.uuid4(),
        ProjectResourceReference(fallback_id),
        transform=LayerTransform(dx=4.0, dy=2.0),
        role="placed",
    )
    second = CompositionLayerInstance(
        uuid.uuid4(),
        ProjectResourceReference(fallback_id),
        transform=LayerTransform(dx=20.0, dy=2.0),
        role="placed",
    )
    third = CompositionLayerInstance(
        uuid.uuid4(),
        ProjectResourceReference(no_fallback_id),
        role="placed",
    )
    assert layers.add_layer(image_id, first)
    assert layers.add_layer(image_id, second)
    assert layers.add_layer(image_id, third)
    path = tmp_path / "placed.qpc"
    codec = CompositionArchiveCodec()
    codec.write(
        capture_composition(
            image_id,
            _composition_owner(
                layers,
                _document(image_id, 16, 12),
                owners.resources,
            ),
            owners.masks,
            owners.rasters,
            placed_assets,
            owners.vectors,
        ),
        path,
    )

    with zipfile.ZipFile(path) as container:
        manifest = json.loads(container.read("manifest.json"))
        placed_resources = [
            item for item in manifest["resources"] if item["kind"] == "linked-raster"
        ]
        assert len(placed_resources) == 2
        assert f"placed/{fallback_id}.npy" in container.namelist()
        assert f"placed/{no_fallback_id}.npy" not in container.namelist()
    decoded = codec.read(path)
    fallback = decoded.placed_assets[fallback_id]
    no_fallback = decoded.placed_assets[no_fallback_id]
    assert fallback.image == fallback_image
    assert fallback.source_path == tmp_path / "offline-fallback.png"
    assert no_fallback.image is None
    assert no_fallback.status is PlacedAssetStatus.MISSING
    assert no_fallback.error

    restored_owners = _resource_owners()
    restored_layers = CompositionLayerStore(CompositionResourceLifetime())
    _ensure_default(
        restored_layers,
        restored_owners.placed_assets,
        image_id,
        image_id,
        16,
        12,
    )
    CompositionArchiveRestorer(
        compositions=_composition_owner(
            restored_layers,
            _document(image_id, 16, 12),
            restored_owners.resources,
        ),
        masks=restored_owners.masks,
        rasters=restored_owners.rasters,
        placed_assets=restored_owners.placed_assets,
        vectors=restored_owners.vectors,
    ).restore(decoded)
    assert restored_owners.placed_assets.get(fallback_id).image == fallback_image
    assert restored_owners.placed_assets.get(no_fallback_id).image is None


def test_vector_documents_round_trip_semantics_and_reject_invalid_payloads(
    tmp_path,
) -> None:
    """Archives should retain vector semantics and reject malformed payloads."""
    image_id = uuid.uuid4()
    owners = _resource_owners()
    layers = CompositionLayerStore(CompositionResourceLifetime())
    _ensure_default(layers, owners.placed_assets, image_id, image_id, 64, 48)
    vectors = owners.vectors
    document = vectors.create(RasterBounds(0, 0, 64, 48))
    vector_object = VectorObject(
        object_id=uuid.uuid4(),
        kind=VectorObjectKind.PATH,
        local_bounds=(4.0, 5.0, 35.0, 23.0),
        transform=LayerTransform(m11=1.2, m22=0.8, dx=3.0, dy=-2.0),
        style=VectorStyle(
            fill=QColor(20, 180, 90, 140),
            stroke=QColor(240, 210, 30),
            stroke_width=4.5,
            dash_pattern=(3.0, 2.0),
            fill_rule=VectorFillRule.EVEN_ODD,
        ),
        path=(
            VectorPathCommand(
                VectorPathCommandKind.MOVE,
                (QPointF(4.0, 5.0),),
            ),
            VectorPathCommand(
                VectorPathCommandKind.CUBIC,
                (QPointF(10.0, 2.0), QPointF(30.0, 35.0), QPointF(39.0, 28.0)),
            ),
            VectorPathCommand(VectorPathCommandKind.CLOSE),
        ),
    )
    document = document.add(vector_object)
    text_content = VectorTextContent(
        "Semantic 😀\nمرحبا",
        VectorTextStyle(("Missing CuteCanvas Font", "Arial"), 26.0),
        (
            VectorTextSpan(
                9,
                1,
                VectorTextStyle(("Segoe UI Emoji",), 30.0, color=QColor(220, 30, 90)),
            ),
        ),
        VectorParagraphStyle(
            VectorTextAlignment.RIGHT,
            VectorTextDirection.RIGHT_TO_LEFT,
            1.2,
        ),
    )
    document = document.add(
        VectorObject(
            object_id=uuid.uuid4(),
            kind=VectorObjectKind.TEXT,
            local_bounds=(6.0, 8.0, 50.0, 34.0),
            transform=LayerTransform(dx=1.5, dy=2.5),
            style=VectorStyle(fill=None, stroke=None, stroke_width=0.0),
            text=text_content,
        )
    )
    assert vectors.replace(document)
    layer = CompositionLayerInstance(
        layer_id=uuid.uuid4(),
        source=ProjectResourceReference(document.vector_id),
        transform=LayerTransform(m11=0.9, m12=0.2, m21=-0.1, m22=1.1),
        interaction=LayerInteractionPolicy(selectable=True, movable=True),
        role="vector",
    )
    assert layers.add_layer(image_id, layer)
    stack = layers.layers_for_composition(image_id)
    masked_base = replace(
        stack[0],
        effects=(
            VectorMaskEffect(
                ProjectResourceReference(document.vector_id),
                LayerTransform(dx=2.0, dy=1.0),
                (vector_object.object_id,),
                True,
            ),
        ),
    )
    assert layers.replace_layers(image_id, (masked_base, layer))
    path = tmp_path / "vector.qpc"
    codec = CompositionArchiveCodec()
    codec.write(
        capture_composition(
            image_id,
            _composition_owner(
                layers,
                _document(image_id, 64, 48),
                owners.resources,
            ),
            owners.masks,
            owners.rasters,
            owners.placed_assets,
            vectors,
        ),
        path,
    )

    decoded = codec.read(path)
    assert decoded.vectors[document.vector_id] == document
    assert decoded.layer_stacks[image_id][0].effects == masked_base.effects
    restored_owners = _resource_owners()
    restored_layers = CompositionLayerStore(CompositionResourceLifetime())
    _ensure_default(
        restored_layers,
        restored_owners.placed_assets,
        image_id,
        image_id,
        64,
        48,
    )
    CompositionArchiveRestorer(
        compositions=_composition_owner(
            restored_layers,
            _document(image_id, 64, 48),
            restored_owners.resources,
        ),
        masks=restored_owners.masks,
        rasters=restored_owners.rasters,
        placed_assets=restored_owners.placed_assets,
        vectors=restored_owners.vectors,
    ).restore(decoded)
    assert restored_owners.vectors.get(document.vector_id) == document
    assert restored_layers.layers_for_composition(image_id)[0].effects == (
        masked_base.effects
    )

    invalid_text_path = tmp_path / "invalid-vector-text.qpc"
    with (
        zipfile.ZipFile(path, "r") as source,
        zipfile.ZipFile(invalid_text_path, "w") as target,
    ):
        manifest = json.loads(source.read("manifest.json"))
        vector_resource = next(
            resource
            for resource in manifest["resources"]
            if resource["kind"] == "vector"
        )
        vector_resource["payload"]["objects"][1]["text"]["spans"][0]["start"] = 999_999
        target.writestr("manifest.json", json.dumps(manifest))
        for name in source.namelist():
            if name != "manifest.json":
                target.writestr(name, source.read(name))
    with pytest.raises(ValueError, match="ordered, non-overlapping, and in range"):
        codec.read(invalid_text_path)

    invalid_path = tmp_path / "invalid-effects.qpc"
    with (
        zipfile.ZipFile(path, "r") as source,
        zipfile.ZipFile(invalid_path, "w") as target,
    ):
        invalid_manifest = json.loads(source.read("manifest.json"))
        invalid_manifest["documents"][0]["instances"][0]["effects"] = {}
        for name in source.namelist():
            payload = (
                json.dumps(invalid_manifest).encode("utf-8")
                if name == "manifest.json"
                else source.read(name)
            )
            target.writestr(name, payload)
    with pytest.raises(TypeError, match="layer effects must be a list"):
        codec.read(invalid_path)


def test_archive_restore_rolls_back_placed_assets_after_late_failure() -> None:
    """A late layer failure must restore prior pixels, provenance, and instances."""
    image_id = uuid.uuid4()
    asset_id = uuid.uuid4()
    source_owners = _resource_owners()
    source_layers = CompositionLayerStore(CompositionResourceLifetime())
    _ensure_default(
        source_layers,
        source_owners.placed_assets,
        image_id,
        image_id,
        8,
        6,
    )
    incoming_image = QImage(5, 4, QImage.Format_ARGB32_Premultiplied)
    incoming_image.fill(QColor("blue"))
    source_owners.placed_assets.create_embedded(incoming_image, asset_id=asset_id)
    incoming_layer = CompositionLayerInstance(
        layer_id=uuid.uuid4(),
        source=ProjectResourceReference(asset_id),
        role="placed",
    )
    assert source_layers.add_layer(image_id, incoming_layer)
    archive = capture_composition(
        image_id,
        _composition_owner(
            source_layers,
            _document(image_id, 8, 6),
            source_owners.resources,
        ),
        source_owners.masks,
        source_owners.rasters,
        source_owners.placed_assets,
        source_owners.vectors,
    )

    restored_owners = _resource_owners()
    restored_layers = _FailingOnceLayerStore(CompositionResourceLifetime())
    _ensure_default(
        restored_layers,
        restored_owners.placed_assets,
        image_id,
        image_id,
        8,
        6,
    )
    previous_layers = restored_layers.layers_for_composition(image_id)
    previous_image = QImage(3, 2, QImage.Format_ARGB32_Premultiplied)
    previous_image.fill(QColor("red"))
    restored_owners.placed_assets.create_embedded(previous_image, asset_id=asset_id)
    previous_asset = restored_owners.placed_assets.get(asset_id)
    restored_layers.fail_next_replacement = True

    with pytest.raises(RuntimeError, match="injected layer publication failure"):
        CompositionArchiveRestorer(
            compositions=_composition_owner(
                restored_layers,
                _document(image_id, 8, 6),
                restored_owners.resources,
            ),
            masks=restored_owners.masks,
            rasters=restored_owners.rasters,
            placed_assets=restored_owners.placed_assets,
            vectors=restored_owners.vectors,
        ).restore(archive)

    assert restored_layers.layers_for_composition(image_id) == previous_layers
    assert restored_owners.placed_assets.get(asset_id) == previous_asset
