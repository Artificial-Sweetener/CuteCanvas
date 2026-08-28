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
"""Authoritative CuteCanvas project-resource graph contracts."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

import pytest
from PySide6.QtCore import QRect, QRectF, QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest

from cutecanvas import CuteCanvas, VectorShapeKind, VectorStyle
from cutecanvas.placed import store as placed_store_module
from cutecanvas.placed.model import FileFingerprint
from cutecanvas.placed.store import PlacedAssetStore
from cutecanvas.raster.assets import EditableRasterAssetStore
from cutecanvas.resources import ProjectResourceKind, ProjectResourceStore
from cutecanvas_test_support.config import fixed_cache_config
from cutecanvas_test_support.harness.timing import completion_clock
from qpane.sdk.scene import RasterBounds


def _wait_for_rasterization(
    qapp,
    completions: list[tuple],
    request_id: uuid.UUID,
) -> tuple:
    """Pump Qt until one generic rasterization request terminates."""
    deadline = completion_clock() + 3.0
    while completion_clock() < deadline:
        qapp.processEvents()
        matching = [item for item in completions if item[0] == request_id]
        if matching:
            return matching[-1]
        time.sleep(0.002)
    raise AssertionError("layer rasterization did not complete")


def test_shared_resource_revision_invalidates_nested_dependents_once() -> None:
    """Editing shared content must invalidate every transitive composition resource."""
    changed = []
    resources = ProjectResourceStore(changed=changed.append)
    raster = resources.create(ProjectResourceKind.RASTER, editable=True)
    nested = resources.create(
        ProjectResourceKind.COMPOSITION,
        editable=True,
        dependencies=(raster.resource_id,),
    )
    parent = resources.create(
        ProjectResourceKind.COMPOSITION,
        editable=True,
        dependencies=(nested.resource_id,),
    )
    changed.clear()

    affected = resources.touch(raster.resource_id)

    assert affected == (
        raster.resource_id,
        nested.resource_id,
        parent.resource_id,
    )
    assert [record.resource_id for record in changed] == list(affected)
    assert all(resources.get(item).revision == 1 for item in affected)


def test_resource_dependency_cycle_rejection_is_atomic() -> None:
    """Cycle attempts must preserve the previous dependency graph and revisions."""
    resources = ProjectResourceStore()
    child = resources.create(ProjectResourceKind.COMPOSITION, editable=True)
    parent = resources.create(
        ProjectResourceKind.COMPOSITION,
        editable=True,
        dependencies=(child.resource_id,),
    )
    revision = resources.revision

    with pytest.raises(ValueError, match="acyclic"):
        resources.set_dependencies(child.resource_id, (parent.resource_id,))

    assert resources.revision == revision
    assert resources.get(child.resource_id).dependencies == frozenset()
    assert resources.dependents(child.resource_id) == (parent.resource_id,)


def test_reference_stays_stable_when_authoritative_resource_kind_changes() -> None:
    """Provenance transitions must not force every referencing layer to be rewritten."""
    resources = ProjectResourceStore()
    linked = resources.create(ProjectResourceKind.LINKED_RASTER, editable=False)
    reference = linked.reference

    resources.set_kind(linked.resource_id, ProjectResourceKind.IMPORTED_RASTER)

    resolved = resources.resolve(reference)
    assert resolved is not None
    assert resolved.kind is ProjectResourceKind.IMPORTED_RASTER
    assert resolved.reference == reference


def test_resource_removal_preserves_live_dependencies() -> None:
    """A dependency cannot disappear while another project resource references it."""
    resources = ProjectResourceStore()
    source = resources.create(ProjectResourceKind.LINKED_RASTER, editable=False)
    composition = resources.create(
        ProjectResourceKind.COMPOSITION,
        editable=True,
        dependencies=(source.resource_id,),
    )

    with pytest.raises(ValueError, match="dependents"):
        resources.remove(source.resource_id)

    assert resources.remove(composition.resource_id)
    assert resources.remove(source.resource_id)
    assert resources.records() == ()


def test_missing_dependency_and_duplicate_identity_fail_without_mutation() -> None:
    """Invalid graph creation must not partially install a project resource."""
    resources = ProjectResourceStore()
    resource_id = uuid.uuid4()

    with pytest.raises(KeyError, match="dependency"):
        resources.create(
            ProjectResourceKind.COMPOSITION,
            editable=True,
            dependencies=(uuid.uuid4(),),
        )
    resources.create(
        ProjectResourceKind.RASTER,
        editable=True,
        resource_id=resource_id,
    )
    with pytest.raises(ValueError, match="already exists"):
        resources.create(
            ProjectResourceKind.VECTOR,
            editable=True,
            resource_id=resource_id,
        )

    assert tuple(record.resource_id for record in resources.records()) == (resource_id,)


def test_editable_raster_mutation_advances_authoritative_resource_revision() -> None:
    """Pixel storage must publish through the project resource rather than a shadow counter."""
    resources = ProjectResourceStore()
    rasters = EditableRasterAssetStore(resources)
    image = QImage(32, 24, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(0, 0, 0, 0))
    asset = rasters.create(image)
    before = resources.get(asset.raster_id)
    assert before is not None

    def fill_patch(pixels) -> bool:
        """Fill the writable patch and report a content change."""
        pixels.fill(255)
        return True

    changed = asset.surface.mutate_patch(
        RasterBounds.from_qrect(QRect(4, 3, 5, 6)),
        fill_patch,
    )

    after = resources.get(asset.raster_id)
    assert changed
    assert after is not None
    assert after.revision == before.revision + 1


def test_imported_and_linked_pixels_share_project_resource_identity() -> None:
    """Provenance transitions must retain one resource identity and revision stream."""
    resources = ProjectResourceStore()
    assets = PlacedAssetStore(resources)
    image = QImage(40, 30, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(10, 20, 30, 255))
    path = Path("source.png")
    asset_id = assets.create_linked(
        image,
        path,
        FileFingerprint(120, 400),
        keep_fallback=True,
    )
    linked = resources.get(asset_id)
    assert linked is not None
    assert linked.kind is ProjectResourceKind.LINKED_RASTER
    assert not linked.editable

    assert assets.embed(asset_id) is not None

    embedded = resources.get(asset_id)
    assert embedded is not None
    assert embedded.kind is ProjectResourceKind.IMPORTED_RASTER
    assert embedded.resource_id == linked.resource_id
    assert embedded.revision == linked.revision + 1
    assert assets.remove(asset_id)
    assert resources.get(asset_id) is None


def test_rejected_placed_image_preparation_preserves_authoritative_pixels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fallible derived-bounds update must not publish partial image state."""
    resources = ProjectResourceStore()
    assets = PlacedAssetStore(resources)
    original = QImage(40, 30, QImage.Format.Format_ARGB32_Premultiplied)
    original.fill(QColor(10, 20, 30, 255))
    asset_id = assets.create_embedded(original)
    original_asset_revision = assets.revision
    original_resource = resources.get(asset_id)
    assert original_resource is not None

    def reject_bounds(_image: QImage) -> QRectF | None:
        """Simulate native-memory rejection before authoritative publication."""
        raise MemoryError("simulated content-bounds contention")

    monkeypatch.setattr(placed_store_module, "_image_content_bounds", reject_bounds)
    replacement = QImage(40, 30, QImage.Format.Format_ARGB32_Premultiplied)
    replacement.fill(QColor(200, 100, 50, 255))

    with pytest.raises(MemoryError, match="simulated content-bounds contention"):
        assets.replace_embedded(asset_id, replacement)

    retained = assets.get(asset_id)
    retained_resource = resources.get(asset_id)
    assert retained is not None and retained.image is not None
    assert retained.image.pixelColor(1, 1) == QColor(10, 20, 30, 255)
    assert assets.revision == original_asset_revision
    assert retained_resource == original_resource


def test_layer_duplicates_share_until_an_undoable_resource_fork(qapp) -> None:
    """Generic layer duplication must share content until one instance is forked."""
    canvas = CuteCanvas(features=())
    image = QImage(32, 24, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(0, 0, 0, 0))
    try:
        canvas.createComposition(QRectF(0.0, 0.0, 64.0, 48.0))
        layer_id = canvas.addEditableRasterLayer(image, label="Shared pixels")
        scene = canvas.currentScene()
        assert layer_id is not None and scene is not None
        duplicate_id = canvas.duplicateLayer(scene.scene_id, layer_id)
        assert duplicate_id is not None
        shared = canvas.currentScene()
        assert shared is not None
        source_ids = {layer.layer_id: layer.source_id for layer in shared.layers}
        assert source_ids[layer_id] == source_ids[duplicate_id]

        fork_id = canvas.forkLayerResource(scene.scene_id, duplicate_id)
        assert fork_id is not None
        forked = canvas.currentScene()
        assert forked is not None
        forked_sources = {layer.layer_id: layer.source_id for layer in forked.layers}
        assert forked_sources[layer_id] != forked_sources[duplicate_id]
        assert forked_sources[duplicate_id] == fork_id

        assets = canvas._editable_raster_assets
        assert assets is not None
        original = assets.get(forked_sources[layer_id])
        independent = assets.get(forked_sources[duplicate_id])
        assert original is not None and independent is not None
        assert original.surface.mutate_patch(
            RasterBounds.from_qrect(QRect(0, 0, 8, 8)),
            lambda pixels: (pixels.fill(255), True)[1],
        )
        assert (
            original.surface.snapshot_qimage() != independent.surface.snapshot_qimage()
        )

        assert canvas.undoSceneEdit()
        undone = canvas.currentScene()
        assert undone is not None
        undone_sources = {layer.layer_id: layer.source_id for layer in undone.layers}
        assert undone_sources[layer_id] == undone_sources[duplicate_id]
        assert canvas.redoSceneEdit()
        redone = canvas.currentScene()
        assert redone is not None
        redone_sources = {layer.layer_id: layer.source_id for layer in redone.layers}
        assert redone_sources[duplicate_id] == fork_id
    finally:
        canvas.deleteLater()
        qapp.processEvents()


def test_editor_handles_share_fork_and_place_project_resources(qapp) -> None:
    """Focused handles must expose the complete ordinary resource workflow."""
    canvas = CuteCanvas(features=())
    image = QImage(24, 18, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(30, 90, 180, 255))
    try:
        source_id = canvas.createCompositionFromImage(image, title="Source")
        source = canvas.editor.compositions.get(source_id)
        target = canvas.editor.compositions.create(
            QRectF(0.0, 0.0, 96.0, 72.0),
            title="Target",
        )
        source = canvas.editor.compositions.get(source_id)
        assert source is not None

        nested = target.place_composition(source)
        assert nested is not None
        assert nested.resource_id == source_id
        duplicate = nested.duplicate()
        assert duplicate is not None
        assert duplicate.resource_id == nested.resource_id

        fork_id = duplicate.fork_resource()

        assert fork_id is not None
        assert duplicate.resource_id == fork_id
        assert nested.resource_id == source_id
    finally:
        canvas.deleteLater()
        qapp.processEvents()


def test_nested_document_cycle_rejection_preserves_layers_and_history(qapp) -> None:
    """A cyclic placement attempt must not mutate either document or its history."""
    canvas = CuteCanvas(features=())
    try:
        child_id = canvas.createComposition(
            QRectF(0.0, 0.0, 32.0, 24.0),
            title="Child",
        )
        parent_id = canvas.createComposition(
            QRectF(0.0, 0.0, 64.0, 48.0),
            title="Parent",
        )
        child_layer_id = canvas.placeComposition(child_id)
        assert child_layer_id is not None
        parent_layers = canvas.compositionService().layers.layers_for_composition(
            parent_id
        )
        assert len(parent_layers) == 1

        canvas.openComposition(child_id)
        assert canvas.currentCompositionID() == child_id
        child_layers_before = canvas.compositionService().layers.layers_for_composition(
            child_id
        )
        graph_revision = canvas._project_resources.revision

        with pytest.raises(ValueError, match="acyclic"):
            canvas.placeComposition(parent_id)

        assert (
            canvas.compositionService().layers.layers_for_composition(child_id)
            == child_layers_before
        )
        assert canvas._project_resources.revision == graph_revision
        assert (
            canvas.compositionService().layers.layers_for_composition(parent_id)
            == parent_layers
        )
    finally:
        canvas.deleteLater()
        qapp.processEvents()


def test_nested_document_dependencies_invalidate_parent_render_revision(qapp) -> None:
    """Editing a child document must invalidate every parent sampled revision."""
    canvas = CuteCanvas(features=())
    image = QImage(16, 12, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(20, 80, 160, 255))
    try:
        child_id = canvas.createComposition(
            QRectF(0.0, 0.0, 32.0, 24.0),
            title="Child",
        )
        parent_id = canvas.createComposition(
            QRectF(0.0, 0.0, 64.0, 48.0),
            title="Parent",
        )
        assert canvas.placeComposition(child_id) is not None
        resources = canvas._project_resources
        parent_before = resources.get(parent_id)
        child_before = resources.get(child_id)
        assert parent_before is not None and child_before is not None

        canvas.openComposition(child_id)
        assert canvas.currentCompositionID() == child_id
        assert canvas.addEditableRasterLayer(image) is not None

        parent_after = resources.get(parent_id)
        child_after = resources.get(child_id)
        assert parent_after is not None and child_after is not None
        assert child_after.revision > child_before.revision
        assert parent_after.revision > parent_before.revision
    finally:
        canvas.deleteLater()
        qapp.processEvents()


@pytest.mark.interactive_performance
def test_nested_document_renders_through_the_mounted_sampled_pipeline(qapp) -> None:
    """A nested document must become visible through normal asynchronous painting."""
    canvas = CuteCanvas(config=fixed_cache_config(), features=())
    canvas.resize(320, 240)
    image = QImage(64, 48, QImage.Format.Format_ARGB32_Premultiplied)
    expected = QColor(220, 30, 40, 255)
    image.fill(expected)
    try:
        canvas.show()
        child_id = canvas.createCompositionFromImage(image, title="Child")
        canvas.createComposition(
            QRectF(0.0, 0.0, 64.0, 48.0),
            title="Parent",
        )
        assert canvas.placeComposition(child_id) is not None

        observed = QColor()
        deadline = completion_clock() + 0.5
        while completion_clock() < deadline:
            qapp.processEvents()
            frame = canvas.grab().toImage()
            observed = frame.pixelColor(frame.width() // 2, frame.height() // 2)
            if observed == expected:
                break
            QTest.qWait(5)

        assert observed == expected
    finally:
        canvas.deleteLater()
        qapp.processEvents()


def test_generic_rasterization_routes_imported_and_vector_resources(qapp) -> None:
    """One public command must convert every supported leaf resource kind."""
    canvas = CuteCanvas(features=())
    image = QImage(32, 24, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(20, 60, 180, 255))
    completions: list[tuple] = []
    canvas.layerRasterizationCompleted.connect(
        lambda *values: completions.append(tuple(values))
    )
    try:
        canvas.createComposition(QRectF(0.0, 0.0, 96.0, 72.0))
        imported_layer = canvas.placeEmbeddedAsset(image, label="Imported")
        scene = canvas.currentScene()
        assert imported_layer is not None and scene is not None

        imported_request = canvas.rasterizeLayer(scene.scene_id, imported_layer)
        assert imported_request is not None
        assert _wait_for_rasterization(
            qapp,
            completions,
            imported_request,
        )[
            3:
        ] == (True, "")
        imported_state = next(
            layer
            for layer in canvas.currentScene().layers
            if layer.layer_id == imported_layer
        )
        assert imported_state.source_kind == "raster"

        vector_layer = canvas.createVectorLayer(QSize(48, 36), label="Vector")
        assert vector_layer is not None
        assert canvas.addVectorShape(
            scene.scene_id,
            vector_layer,
            VectorShapeKind.RECTANGLE,
            QRectF(4.0, 5.0, 30.0, 20.0),
            VectorStyle(fill=QColor(220, 80, 30, 255)),
        )
        vector_request = canvas.rasterizeLayer(scene.scene_id, vector_layer)
        assert vector_request is not None
        assert _wait_for_rasterization(
            qapp,
            completions,
            vector_request,
        )[
            3:
        ] == (True, "")
        vector_state = next(
            layer
            for layer in canvas.currentScene().layers
            if layer.layer_id == vector_layer
        )
        assert vector_state.source_kind == "raster"
    finally:
        canvas.deleteLater()
        qapp.processEvents()


def test_nested_document_rasterization_preserves_pixels_and_history(qapp) -> None:
    """Nested sampling must replace one layer atomically and undo exactly."""
    canvas = CuteCanvas(features=())
    image = QImage(40, 30, QImage.Format.Format_ARGB32_Premultiplied)
    expected = QColor(170, 40, 210, 255)
    image.fill(expected)
    completions: list[tuple] = []
    canvas.layerRasterizationCompleted.connect(
        lambda *values: completions.append(tuple(values))
    )
    try:
        child_id = canvas.createCompositionFromImage(image, title="Child")
        canvas.createComposition(
            QRectF(0.0, 0.0, 80.0, 60.0),
            title="Parent",
        )
        layer_id = canvas.placeComposition(
            child_id,
            placement=QRectF(7.0, 9.0, 60.0, 45.0),
        )
        scene = canvas.currentScene()
        assert layer_id is not None and scene is not None
        before = next(layer for layer in scene.layers if layer.layer_id == layer_id)

        request_id = canvas.rasterizeLayer(scene.scene_id, layer_id)
        assert request_id is not None
        assert _wait_for_rasterization(
            qapp,
            completions,
            request_id,
        )[
            3:
        ] == (True, "")
        after = next(
            layer
            for layer in canvas.currentScene().layers
            if layer.layer_id == layer_id
        )
        assert after.source_kind == "raster"
        assert after.placement == before.placement
        assets = canvas._editable_raster_assets
        assert assets is not None
        raster = assets.get(after.source_id)
        assert raster is not None
        raster_image = raster.surface.snapshot_qimage()
        assert raster_image.pixelColor(raster_image.rect().center()) == expected

        assert canvas.undoSceneEdit()
        undone = next(
            layer
            for layer in canvas.currentScene().layers
            if layer.layer_id == layer_id
        )
        assert undone.source_kind == "composition"
        assert undone.source_id == child_id
        assert undone.placement == before.placement
        assert canvas.redoSceneEdit()
        redone = next(
            layer
            for layer in canvas.currentScene().layers
            if layer.layer_id == layer_id
        )
        assert redone.source_id == after.source_id
        assert redone.placement == after.placement
    finally:
        canvas.deleteLater()
        qapp.processEvents()
