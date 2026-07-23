#    QPane + CuteCanvas - High-performance PySide6 rendering and editing
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

"""Tests for public catalog-backed scene composition."""

from __future__ import annotations

import uuid

import pytest
from cutecanvas import (
    CatalogLayerRequest,
    ComparisonOrientation,
    CompositionLayerClip,
    CompositionRequest,
    CompositionTemplate,
    CuteCanvas,
    LayerPolicy,
    SceneSnapshot,
    TemplateBindings,
    TemplateLayer,
)
from PySide6.QtCore import QPoint, QPointF, QRectF, QSize
from PySide6.QtGui import QColor, QImage, Qt, QTransform
from PySide6.QtTest import QTest
from qpane.scene.affine import LayerTransform
from qpane.scene.identity import catalog_source_asset_key
from qpane.scene.model import LayerPlacement
from qpane.scene.render_plan import RasterLayerRenderItem, RenderStrategy

from examples.demonstration import scene_composition
from tests.helpers.render_compare import rendered_overscanned_widget_frame


def _solid_image(
    width: int = 100,
    height: int = 100,
    color: Qt.GlobalColor | QColor = Qt.white,
) -> QImage:
    """Return a solid image for scene tests."""
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(color)
    return image


def _cleanup_qpane(qpane: CuteCanvas, qapp) -> None:
    """Release a CuteCanvas through Qt's event loop."""
    qpane.deleteLater()
    qapp.processEvents()


def _load_images(
    qpane: CuteCanvas, *, large: bool = False
) -> tuple[uuid.UUID, uuid.UUID]:
    """Load two catalog images and return their IDs."""
    first_id, second_id = uuid.uuid4(), uuid.uuid4()
    size = 1024 if large else 100
    qpane.setImagesByID(
        CuteCanvas.imageMapFromLists(
            [
                _solid_image(size, size, Qt.red),
                _solid_image(size, size, Qt.blue),
            ],
            [None, None],
            [first_id, second_id],
        ),
        first_id,
    )
    return first_id, second_id


def _scene_request(first_id: uuid.UUID, second_id: uuid.UUID) -> CompositionRequest:
    """Return a two-layer public scene request."""
    return CompositionRequest(
        composition_id=None,
        title="Contact sheet",
        bounds=QRectF(0.0, 0.0, 200.0, 100.0),
        layers=(
            CatalogLayerRequest(
                layer_id=uuid.uuid4(),
                image_id=first_id,
                placement=QRectF(0.0, 0.0, 100.0, 100.0),
                role="thumbnail",
                metadata={"slot": 0},
            ),
            CatalogLayerRequest(
                layer_id=uuid.uuid4(),
                image_id=second_id,
                placement=QRectF(100.0, 0.0, 100.0, 100.0),
                role="thumbnail",
                metadata={"slot": 1},
            ),
        ),
    )


def _clipped_scene_request(
    image_id: uuid.UUID,
    clip: CompositionLayerClip,
) -> CompositionRequest:
    """Return a one-layer scene request using ``clip``."""
    return CompositionRequest(
        composition_id=None,
        title="Clipped scene",
        bounds=QRectF(0.0, 0.0, 100.0, 100.0),
        layers=(
            CatalogLayerRequest(
                layer_id=uuid.uuid4(),
                image_id=image_id,
                placement=QRectF(0.0, 0.0, 100.0, 100.0),
                clip=clip,
            ),
        ),
    )


def _assert_rect(
    rect: QRectF,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
) -> None:
    """Assert QRectF coordinates with float tolerance."""
    assert rect.x() == pytest.approx(x)
    assert rect.y() == pytest.approx(y)
    assert rect.width() == pytest.approx(width)
    assert rect.height() == pytest.approx(height)


def test_fit_scene_rect_preserves_portrait_aspect_inside_landscape_target() -> None:
    """fitSceneRect should fit portrait sources without distortion."""
    rect = CuteCanvas.fitSceneRect(QSize(200, 400), QRectF(0.0, 0.0, 320.0, 240.0))

    _assert_rect(rect, x=100.0, y=0.0, width=120.0, height=240.0)


def test_fit_scene_rect_preserves_landscape_aspect_inside_portrait_target() -> None:
    """fitSceneRect should fit landscape sources without distortion."""
    rect = CuteCanvas.fitSceneRect(QSize(400, 200), QRectF(0.0, 0.0, 100.0, 300.0))

    _assert_rect(rect, x=0.0, y=125.0, width=100.0, height=50.0)


def test_fill_scene_rect_covers_target_without_distortion() -> None:
    """fillSceneRect should cover the target while preserving source aspect."""
    rect = CuteCanvas.fillSceneRect(QSize(200, 400), QRectF(0.0, 0.0, 320.0, 240.0))

    _assert_rect(rect, x=0.0, y=-200.0, width=320.0, height=640.0)


def test_scene_rect_helpers_center_zero_area_targets() -> None:
    """Aspect helpers should return centered zero-area rectangles for empty slots."""
    rect = CuteCanvas.fitSceneRect(QSize(10, 20), QRectF(10.0, 20.0, 0.0, 240.0))

    _assert_rect(rect, x=10.0, y=140.0, width=0.0, height=0.0)


def test_scene_rect_helpers_reject_invalid_dimensions() -> None:
    """Aspect helpers should reject invalid source and target dimensions."""
    with pytest.raises(ValueError, match="source_size dimensions must be positive"):
        CuteCanvas.fitSceneRect(QSize(0, 10), QRectF(0.0, 0.0, 10.0, 10.0))
    with pytest.raises(ValueError, match="target_rect dimensions must be non-negative"):
        CuteCanvas.fillSceneRect(QSize(10, 10), QRectF(0.0, 0.0, -1.0, 10.0))


def test_layer_index_reorders_one_stack_and_replays_exactly(qapp) -> None:
    """Public z-order edits should use the composition's atomic stack history."""
    qpane = CuteCanvas(features=())
    try:
        first_id, second_id = _load_images(qpane)
        request = _scene_request(first_id, second_id)
        qpane.composeScene(request, activate=True)
        scene = qpane.currentScene()
        assert scene is not None
        bottom_id, top_id = (layer.layer_id for layer in scene.layers)

        assert qpane.setLayerIndex(scene.scene_id, bottom_id, 1)
        assert tuple(layer.layer_id for layer in qpane.currentScene().layers) == (
            top_id,
            bottom_id,
        )
        assert qpane.undoSceneEdit()
        assert tuple(layer.layer_id for layer in qpane.currentScene().layers) == (
            bottom_id,
            top_id,
        )
        assert qpane.redoSceneEdit()
        assert tuple(layer.layer_id for layer in qpane.currentScene().layers) == (
            top_id,
            bottom_id,
        )
    finally:
        _cleanup_qpane(qpane, qapp)


def test_contact_sheet_demo_packs_fitted_thumbnail_placements() -> None:
    """The demo contact sheet should gap actual thumbnails, not wide slots."""
    first_id, second_id, third_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    request = scene_composition.build_contact_sheet_request(
        (first_id, second_id, third_id),
        image_sizes={
            first_id: QSize(200, 400),
            second_id: QSize(200, 400),
            third_id: QSize(200, 400),
        },
        columns=2,
        cell_width=320.0,
        cell_height=240.0,
        gap=16.0,
    )

    first, second, third = (layer.placement for layer in request.layers)
    assert first.width() / first.height() == pytest.approx(0.5)
    assert second.x() - (first.x() + first.width()) == pytest.approx(16.0)
    assert third.x() == pytest.approx(0.0)
    assert third.y() == pytest.approx(256.0)
    assert request.bounds.width() == pytest.approx(256.0)
    assert request.bounds.height() == pytest.approx(496.0)


def test_compose_scene_renders_catalog_layers_and_reuses_pyramids(qapp) -> None:
    """Public scenes should render catalog-backed layers through pyramid assets."""
    qpane = CuteCanvas(features=())
    qpane.resize(200, 100)
    try:
        first_id, second_id = _load_images(qpane)
        request = _scene_request(first_id, second_id)

        changed: list[SceneSnapshot | None] = []
        qpane.sceneChanged.connect(changed.append)
        composition_id = qpane.composeScene(request)
        plan = qpane.view().calculateRenderPlan(is_blank=False)

        assert qpane.currentScene() == changed[-1]
        assert qpane.currentScene().composition_id == composition_id
        assert qpane.currentScene().scene_id == composition_id
        assert composition_id in qpane.compositionIDs()
        assert plan is not None
        raster_items = [
            item
            for item in plan.render_items
            if isinstance(item, RasterLayerRenderItem)
        ]
        assert len(raster_items) == 2
        assert [item.asset_key.source_id for item in raster_items] == [
            first_id,
            second_id,
        ]
        assert [item.pyramid_asset_key for item in raster_items] == [
            catalog_source_asset_key(first_id, revision=1, source_path=None),
            catalog_source_asset_key(second_id, revision=1, source_path=None),
        ]

        qpane.view().allocate_buffers()
        renderer = qpane.view().renderer
        renderer.paint(plan)
        buffer = renderer.get_base_buffer()
        assert buffer is not None
        buffer = rendered_overscanned_widget_frame(
            buffer.copy(),
            renderer.get_subpixel_pan_offset(),
            renderer._viewport_physical_size,
            renderer._BUFFER_OVERSCAN_PHYSICAL_PX,
        )
        assert buffer.pixelColor(50, 50) == QColor(Qt.red)
        assert buffer.pixelColor(150, 50) == QColor(Qt.blue)
    finally:
        _cleanup_qpane(qpane, qapp)


def test_catalog_source_products_are_shared_across_compositions(qapp) -> None:
    """Independent instances of one catalog source must reuse render identity."""
    qpane = CuteCanvas(features=())
    qpane.resize(160, 120)
    try:
        image_id, _other_id = _load_images(qpane)
        first_layer_id = uuid.uuid4()
        first_composition = qpane.composeScene(
            CompositionRequest(
                composition_id=None,
                title="First use",
                bounds=QRectF(0.0, 0.0, 100.0, 100.0),
                layers=(
                    CatalogLayerRequest(
                        layer_id=first_layer_id,
                        image_id=image_id,
                        placement=QRectF(0.0, 0.0, 100.0, 100.0),
                    ),
                ),
            )
        )
        first_plan = qpane.view().calculateRenderPlan(is_blank=False)
        assert first_plan is not None
        first_item = first_plan.render_items[0]

        second_layer_id = uuid.uuid4()
        second_composition = qpane.composeScene(
            CompositionRequest(
                composition_id=None,
                title="Second use",
                bounds=QRectF(0.0, 0.0, 100.0, 100.0),
                layers=(
                    CatalogLayerRequest(
                        layer_id=second_layer_id,
                        image_id=image_id,
                        placement=QRectF(20.0, 10.0, 70.0, 80.0),
                    ),
                ),
            )
        )
        second_plan = qpane.view().calculateRenderPlan(is_blank=False)
        assert second_plan is not None
        second_item = second_plan.render_items[0]

        assert first_composition != second_composition
        assert first_item.asset_key != second_item.asset_key
        assert first_item.pyramid_asset_key == second_item.pyramid_asset_key
        assert first_item.source_image.cacheKey() == second_item.source_image.cacheKey()
    finally:
        _cleanup_qpane(qpane, qapp)


def test_default_and_host_scenes_share_the_composition_instance_store(qapp) -> None:
    """Both compatibility paths must publish from one authoritative layer store."""
    qpane = CuteCanvas(features=())
    qpane.resize(200, 100)
    try:
        first_id, _second_id = _load_images(qpane)
        compositions = qpane.compositionService()
        default_id = compositions.default_composition_for_image(first_id)
        assert default_id is not None
        assert len(compositions.layers.layers_for_composition(default_id)) == 1

        first_layer_id = uuid.uuid4()
        second_layer_id = uuid.uuid4()
        request = CompositionRequest(
            composition_id=None,
            title="Shared source",
            bounds=QRectF(0.0, 0.0, 200.0, 100.0),
            layers=(
                CatalogLayerRequest(
                    layer_id=first_layer_id,
                    image_id=first_id,
                    placement=QRectF(0.0, 0.0, 100.0, 100.0),
                ),
                CatalogLayerRequest(
                    layer_id=second_layer_id,
                    image_id=first_id,
                    placement=QRectF(100.0, 0.0, 100.0, 100.0),
                ),
            ),
        )
        composition_id = qpane.composeScene(request)
        instances = compositions.layers.layers_for_composition(composition_id)

        assert [instance.layer_id for instance in instances] == [
            first_layer_id,
            second_layer_id,
        ]
        assert instances[0].source == instances[1].source
        assert instances[0].transform != instances[1].transform
        assert [layer.layer_id for layer in qpane.currentScene().layers] == [
            first_layer_id,
            second_layer_id,
        ]
    finally:
        _cleanup_qpane(qpane, qapp)


def test_compose_scene_applies_catalog_layer_opacity(qapp) -> None:
    """Public catalog layers should composite using their requested opacity."""
    qpane = CuteCanvas(features=())
    qpane.resize(100, 100)
    try:
        first_id, second_id = _load_images(qpane)
        qpane.composeScene(
            CompositionRequest(
                composition_id=None,
                title="Opacity",
                bounds=QRectF(0.0, 0.0, 100.0, 100.0),
                layers=(
                    CatalogLayerRequest(
                        layer_id=uuid.uuid4(),
                        image_id=first_id,
                        placement=QRectF(0.0, 0.0, 100.0, 100.0),
                    ),
                    CatalogLayerRequest(
                        layer_id=uuid.uuid4(),
                        image_id=second_id,
                        placement=QRectF(0.0, 0.0, 100.0, 100.0),
                        opacity=0.5,
                    ),
                ),
            )
        )
        plan = qpane.view().calculateRenderPlan(is_blank=False)

        assert plan is not None
        assert [item.descriptor.opacity for item in plan.render_items] == [1.0, 0.5]

        qpane.view().allocate_buffers()
        renderer = qpane.view().renderer
        renderer.paint(plan)
        buffer = renderer.get_base_buffer()
        assert buffer is not None
        frame = rendered_overscanned_widget_frame(
            buffer.copy(),
            renderer.get_subpixel_pan_offset(),
            renderer._viewport_physical_size,
            renderer._BUFFER_OVERSCAN_PHYSICAL_PX,
        )
        center = frame.pixelColor(50, 50)
        assert center.alpha() == 255
        assert center.red() == pytest.approx(127, abs=1)
        assert center.green() == 0
        assert center.blue() == pytest.approx(128, abs=1)
    finally:
        _cleanup_qpane(qpane, qapp)


def test_compose_scene_detaches_request_clip(qapp) -> None:
    """Mutating the original clip after composition should not alter stored scene state."""
    qpane = CuteCanvas(features=())
    try:
        first_id, _second_id = _load_images(qpane)
        clip = CompositionLayerClip("scene", QRectF(0.0, 0.0, 10.0, 10.0))

        qpane.composeScene(_clipped_scene_request(first_id, clip))

        scene = qpane.currentScene()
        assert scene is not None
        assert scene.layers[0].clip is not None
        assert scene.layers[0].clip.rect.width() == pytest.approx(10.0)

        clip.rect.setWidth(99.0)

        fresh_scene = qpane.currentScene()
        assert fresh_scene is not None
        assert fresh_scene.layers[0].clip is not None
        assert fresh_scene.layers[0].clip.rect.width() == pytest.approx(10.0)
    finally:
        _cleanup_qpane(qpane, qapp)


def test_current_scene_detaches_returned_clip_snapshot(qapp) -> None:
    """Mutating a returned scene clip should not alter later scene snapshots."""
    qpane = CuteCanvas(features=())
    try:
        first_id, _second_id = _load_images(qpane)
        clip = CompositionLayerClip("scene", QRectF(0.0, 0.0, 12.0, 12.0))

        qpane.composeScene(_clipped_scene_request(first_id, clip))
        scene = qpane.currentScene()
        assert scene is not None
        snapshot_clip = scene.layers[0].clip
        assert snapshot_clip is not None

        snapshot_clip.rect.setWidth(99.0)

        fresh_scene = qpane.currentScene()
        assert fresh_scene is not None
        assert fresh_scene.layers[0].clip is not None
        assert fresh_scene.layers[0].clip.rect.width() == pytest.approx(12.0)
    finally:
        _cleanup_qpane(qpane, qapp)


def test_scene_raster_smoothing_is_decided_per_layer(qapp) -> None:
    """Scene thumbnails should smooth when minified but stay sharp when magnified."""
    qpane = CuteCanvas(features=())
    qpane.resize(110, 50)
    try:
        base_id = uuid.uuid4()
        minified_id = uuid.uuid4()
        magnified_id = uuid.uuid4()
        minified_layer_id = uuid.uuid4()
        magnified_layer_id = uuid.uuid4()
        qpane.setImagesByID(
            CuteCanvas.imageMapFromLists(
                [
                    _solid_image(100, 100, Qt.red),
                    _solid_image(1000, 1000, Qt.blue),
                    _solid_image(10, 10, Qt.green),
                ],
                [None, None, None],
                [base_id, minified_id, magnified_id],
            ),
            base_id,
        )
        qpane.composeScene(
            CompositionRequest(
                composition_id=None,
                title="Scale checks",
                bounds=QRectF(0.0, 0.0, 110.0, 50.0),
                layers=(
                    CatalogLayerRequest(
                        layer_id=uuid.uuid4(),
                        image_id=base_id,
                        placement=QRectF(0.0, 0.0, 10.0, 10.0),
                    ),
                    CatalogLayerRequest(
                        layer_id=minified_layer_id,
                        image_id=minified_id,
                        placement=QRectF(20.0, 0.0, 50.0, 50.0),
                    ),
                    CatalogLayerRequest(
                        layer_id=magnified_layer_id,
                        image_id=magnified_id,
                        placement=QRectF(80.0, 0.0, 30.0, 30.0),
                    ),
                ),
            )
        )

        plan = qpane.view().calculateRenderPlan(is_blank=False)

        assert plan is not None
        raster_items = {
            item.descriptor.layer_id: item
            for item in plan.render_items
            if isinstance(item, RasterLayerRenderItem)
        }
        assert raster_items[minified_layer_id].render_hint_enabled is True
        assert raster_items[magnified_layer_id].render_hint_enabled is False
        assert raster_items[minified_layer_id].pyramid_asset_key == (
            catalog_source_asset_key(minified_id, revision=1, source_path=None)
        )
    finally:
        _cleanup_qpane(qpane, qapp)


def test_compose_scene_validates_public_inputs(qapp) -> None:
    """Public scene activation should reject invalid scenes before mutation."""
    qpane = CuteCanvas(features=())
    try:
        first_id, second_id = _load_images(qpane)
        valid_layer = CatalogLayerRequest(
            layer_id=uuid.uuid4(),
            image_id=first_id,
            placement=QRectF(0.0, 0.0, 100.0, 100.0),
        )
        with pytest.raises(KeyError):
            qpane.composeScene(
                CompositionRequest(
                    composition_id=None,
                    title=None,
                    bounds=QRectF(0.0, 0.0, 100.0, 100.0),
                    layers=(
                        CatalogLayerRequest(
                            layer_id=uuid.uuid4(),
                            image_id=uuid.uuid4(),
                            placement=QRectF(0.0, 0.0, 100.0, 100.0),
                        ),
                    ),
                )
            )
        with pytest.raises(ValueError):
            qpane.composeScene(
                CompositionRequest(
                    composition_id=None,
                    title=None,
                    bounds=QRectF(0.0, 0.0, 100.0, 100.0),
                    layers=(valid_layer, valid_layer),
                )
            )
        with pytest.raises(ValueError):
            qpane.composeScene(
                CompositionRequest(
                    composition_id=None,
                    title=None,
                    bounds=QRectF(0.0, 0.0, 0.0, 100.0),
                    layers=(valid_layer,),
                )
            )
        with pytest.raises(ValueError):
            qpane.composeScene(
                CompositionRequest(
                    composition_id=None,
                    title=None,
                    bounds=QRectF(0.0, 0.0, 100.0, 100.0),
                    layers=(
                        CatalogLayerRequest(
                            layer_id=uuid.uuid4(),
                            image_id=second_id,
                            placement=QRectF(0.0, 0.0, 100.0, 100.0),
                            opacity=1.5,
                        ),
                    ),
                )
            )
        assert qpane.currentScene().layers[0].image_id == first_id
    finally:
        _cleanup_qpane(qpane, qapp)


def test_compose_scene_stores_reopens_and_replaces_composition(qapp) -> None:
    """Layered scenes should behave like stored composition records."""
    qpane = CuteCanvas(features=())
    try:
        first_id, second_id = _load_images(qpane)
        request = _scene_request(first_id, second_id)

        stored_id = qpane.composeScene(request, activate=False)

        assert stored_id in qpane.compositionIDs()
        assert qpane.currentScene().layers[0].image_id == first_id
        entry = qpane.getCompositionSnapshot().compositions[stored_id]
        assert entry.kind == "layered-scene"
        assert entry.current_image_id is None
        assert entry.source_image_ids == (first_id, second_id)
        assert entry.scene_layer_count == 2
        assert entry.scene_bounds == request.bounds

        qpane.openComposition(stored_id)
        assert qpane.currentCompositionID() == stored_id
        assert qpane.currentScene().composition_id == stored_id

        replacement = CompositionRequest(
            composition_id=stored_id,
            title="Replacement",
            bounds=QRectF(0.0, 0.0, 100.0, 100.0),
            layers=(
                CatalogLayerRequest(
                    layer_id=uuid.uuid4(),
                    image_id=second_id,
                    placement=QRectF(0.0, 0.0, 100.0, 100.0),
                ),
            ),
        )
        assert qpane.composeScene(replacement) == stored_id
        assert qpane.currentScene().title == "Replacement"
        assert qpane.currentScene().layers[0].image_id == second_id
    finally:
        _cleanup_qpane(qpane, qapp)


def test_active_scene_replacement_without_activation_refreshes_scene(qapp) -> None:
    """Replacing the active scene in place should refresh content without reselecting."""
    qpane = CuteCanvas(features=())
    qpane.resize(200, 100)
    try:
        first_id, second_id = _load_images(qpane)
        composition_id = qpane.composeScene(_scene_request(first_id, second_id))
        replacement = CompositionRequest(
            composition_id=composition_id,
            title="Active replacement",
            bounds=QRectF(0.0, 0.0, 50.0, 100.0),
            layers=(
                CatalogLayerRequest(
                    layer_id=uuid.uuid4(),
                    image_id=second_id,
                    placement=QRectF(0.0, 0.0, 50.0, 100.0),
                    metadata={"slot": "replacement"},
                ),
            ),
        )
        composition_events = []
        scene_events: list[SceneSnapshot | None] = []
        selection_events = []
        qpane.compositionChanged.connect(composition_events.append)
        qpane.sceneChanged.connect(scene_events.append)
        qpane.compositionSelectionChanged.connect(selection_events.append)

        assert qpane.composeScene(replacement, activate=False) == composition_id

        scene = qpane.currentScene()
        assert len(composition_events) == 1
        assert scene_events == [scene]
        assert selection_events == []
        assert scene is not None
        assert scene.composition_id == composition_id
        assert scene.title == "Active replacement"
        assert scene.bounds == replacement.bounds
        assert [layer.image_id for layer in scene.layers] == [second_id]
        assert scene.layers[0].metadata["slot"] == "replacement"

        plan = qpane.view().calculateRenderPlan(is_blank=False)
        assert plan is not None
        raster_items = [
            item
            for item in plan.render_items
            if isinstance(item, RasterLayerRenderItem)
        ]
        assert len(raster_items) == 1
        assert raster_items[0].asset_key.source_id == second_id
        assert raster_items[0].placement.width == 50.0
    finally:
        _cleanup_qpane(qpane, qapp)


def test_inactive_scene_replacement_without_activation_only_updates_browser(
    qapp,
) -> None:
    """Replacing an inactive scene should not disturb the active render scene."""
    qpane = CuteCanvas(features=())
    try:
        first_id, second_id = _load_images(qpane)
        stored_id = qpane.composeScene(
            _scene_request(first_id, second_id), activate=False
        )
        active_scene = qpane.currentScene()
        replacement = CompositionRequest(
            composition_id=stored_id,
            title="Inactive replacement",
            bounds=QRectF(0.0, 0.0, 50.0, 50.0),
            layers=(
                CatalogLayerRequest(
                    layer_id=uuid.uuid4(),
                    image_id=second_id,
                    placement=QRectF(0.0, 0.0, 50.0, 50.0),
                ),
            ),
        )
        composition_events = []
        scene_events = []
        selection_events = []
        qpane.compositionChanged.connect(composition_events.append)
        qpane.sceneChanged.connect(scene_events.append)
        qpane.compositionSelectionChanged.connect(selection_events.append)

        qpane.composeScene(replacement, activate=False)

        assert len(composition_events) == 1
        assert scene_events == []
        assert selection_events == []
        assert qpane.currentScene() == active_scene
    finally:
        _cleanup_qpane(qpane, qapp)


def test_compose_scene_from_template_expands_bindings(qapp) -> None:
    """Scene templates should expand into stored layered compositions."""
    qpane = CuteCanvas(features=())
    try:
        first_id, second_id = _load_images(qpane)
        template = CompositionTemplate(
            template_id=uuid.uuid4(),
            title="Template title",
            bounds=QRectF(0.0, 0.0, 200.0, 100.0),
            layers=(
                TemplateLayer(
                    layer_id=uuid.uuid4(),
                    source_slot="left",
                    placement=QRectF(0.0, 0.0, 100.0, 100.0),
                    metadata={"slot": "template"},
                ),
                TemplateLayer(
                    layer_id=uuid.uuid4(),
                    source_slot="right",
                    placement=QRectF(100.0, 0.0, 100.0, 100.0),
                ),
            ),
        )
        composition_id = qpane.composeSceneFromTemplate(
            template,
            TemplateBindings(
                composition_id=None,
                title="Bound title",
                catalog_images={
                    "left": first_id,
                    "right": second_id,
                    "ignored": first_id,
                },
                metadata={"left": {"slot": "binding"}},
            ),
        )

        scene = qpane.currentScene()
        assert scene.composition_id == composition_id
        assert scene.title == "Bound title"
        assert [layer.image_id for layer in scene.layers] == [first_id, second_id]
        assert scene.layers[0].metadata["slot"] == "binding"

        with pytest.raises(ValueError):
            qpane.composeSceneFromTemplate(
                template,
                TemplateBindings(
                    composition_id=None,
                    catalog_images={"left": first_id},
                ),
            )
    finally:
        _cleanup_qpane(qpane, qapp)


def test_scene_hit_test_returns_public_layer_metadata_without_selection(qapp) -> None:
    """Public scene hit testing should return opaque host metadata without navigation."""
    qpane = CuteCanvas(features=())
    qpane.resize(200, 100)
    try:
        first_id, second_id = _load_images(qpane)
        qpane.composeScene(_scene_request(first_id, second_id))
        before = qpane.currentImageID()

        hit = qpane.sceneHitTest(QPoint(150, 50))

        assert hit is not None
        assert hit.image_id == second_id
        assert hit.metadata["slot"] == 1
        assert hit.role == "thumbnail"
        assert qpane.currentImageID() == before
    finally:
        _cleanup_qpane(qpane, qapp)


def test_scene_layer_interaction_policy_round_trips_and_updates_generically(
    qapp,
) -> None:
    """Stored scene policy should survive normalization and generic mutation."""
    qpane = CuteCanvas(features=())
    qpane.resize(200, 100)
    try:
        first_id, second_id = _load_images(qpane)
        request = _scene_request(first_id, second_id)
        movable = LayerPolicy(selectable=True, movable=True)
        first = request.layers[0]
        request = CompositionRequest(
            composition_id=request.composition_id,
            title=request.title,
            bounds=request.bounds,
            layers=(
                CatalogLayerRequest(
                    layer_id=first.layer_id,
                    image_id=first.image_id,
                    placement=first.placement,
                    role=first.role,
                    metadata=first.metadata,
                    interaction=movable,
                ),
                request.layers[1],
            ),
        )
        composition_id = qpane.composeScene(request)

        scene = qpane.currentScene()
        assert scene is not None
        assert scene.layers[0].interaction == movable
        plan = qpane.view().calculateRenderPlan(is_blank=False)
        assert plan is not None
        assert plan.render_items[0].descriptor.interaction.selectable is True
        assert plan.render_items[0].descriptor.interaction.movable is True

        moved = QRectF(15.0, 10.0, 100.0, 100.0)
        assert qpane.setLayerPlacement(composition_id, first.layer_id, moved)
        moved_scene = qpane.currentScene()
        assert moved_scene is not None
        assert moved_scene.bounds == request.bounds
        assert moved_scene.layers[0].placement == moved
        assert qpane.sceneEditUndoAvailable()
        assert not qpane.sceneEditRedoAvailable()
        assert qpane.undoSceneEdit()
        assert qpane.currentScene().layers[0].placement == first.placement
        assert qpane.sceneEditRedoAvailable()
        assert qpane.redoSceneEdit()
        assert qpane.currentScene().layers[0].placement == moved

        locked = LayerPolicy()
        assert qpane.setLayerInteractionPolicy(
            composition_id,
            first.layer_id,
            locked,
        )
        assert qpane.currentScene().layers[0].interaction == locked
        assert not qpane.setLayerInteractionPolicy(
            composition_id,
            first.layer_id,
            locked,
        )
        assert not qpane.setLayerPlacement(
            composition_id,
            first.layer_id,
            QRectF(30.0, 20.0, 100.0, 100.0),
        )
    finally:
        _cleanup_qpane(qpane, qapp)


def test_move_interaction_previews_then_commits_generic_layer_placement(qapp) -> None:
    """Move interaction should preview geometry and commit one undoable placement."""
    qpane = CuteCanvas(features=())
    qpane.resize(200, 100)
    try:
        first_id, second_id = _load_images(qpane)
        request = _scene_request(first_id, second_id)
        first = request.layers[0]
        request = CompositionRequest(
            composition_id=request.composition_id,
            title=request.title,
            bounds=request.bounds,
            layers=(
                CatalogLayerRequest(
                    layer_id=first.layer_id,
                    image_id=first.image_id,
                    placement=first.placement,
                    role=first.role,
                    metadata=first.metadata,
                    interaction=LayerPolicy(
                        selectable=True,
                        movable=True,
                    ),
                ),
                request.layers[1],
            ),
        )
        qpane.composeScene(request)
        qpane.show()
        qapp.processEvents()
        initial_plan = qpane.view().calculateRenderPlan(is_blank=False)
        assert initial_plan is not None
        initial_item = initial_plan.render_items[0]
        source_revision = initial_item.descriptor.source_revision
        origin = initial_item.transform.map(QPointF(50.0, 50.0))
        target = initial_item.transform.map(QPointF(70.0, 60.0))

        movement = qpane.sceneLayerMovementInteraction()
        candidate = movement.candidate_at(origin)
        assert candidate is not None
        assert movement.begin(candidate)
        assert movement.update(target)
        preview_plan = qpane.view().calculateRenderPlan(is_blank=False)

        assert preview_plan is not None
        preview = preview_plan.render_items[0].descriptor
        assert preview.placement == LayerPlacement(20.0, 10.0, 100.0, 100.0)
        assert preview.source_revision == source_revision
        assert qpane.currentScene().layers[0].placement == first.placement

        assert movement.finish(target)
        assert qpane.currentScene().layers[0].placement == QRectF(
            20.0,
            10.0,
            100.0,
            100.0,
        )
        assert qpane.sceneEditUndoAvailable()
        assert qpane.undoSceneEdit()
        assert qpane.currentScene().layers[0].placement == first.placement
    finally:
        _cleanup_qpane(qpane, qapp)


def test_public_affine_transform_round_trips_renders_hits_and_undoes(qapp) -> None:
    """Exact affine geometry must remain one public, rendered, undoable value."""
    qpane = CuteCanvas(features=())
    qpane.resize(200, 120)
    try:
        image_id, _second_id = _load_images(qpane)
        layer_id = uuid.uuid4()
        composition_id = qpane.composeScene(
            CompositionRequest(
                composition_id=None,
                title="Affine layer",
                bounds=QRectF(0.0, 0.0, 200.0, 120.0),
                layers=(
                    CatalogLayerRequest(
                        layer_id=layer_id,
                        image_id=image_id,
                        placement=QRectF(10.0, 10.0, 100.0, 100.0),
                        interaction=LayerPolicy(
                            selectable=True,
                            movable=True,
                        ),
                    ),
                ),
            )
        )
        qpane.show()
        qapp.processEvents()
        before = qpane.layerTransform(composition_id, layer_id)
        assert before is not None
        local_bounds = qpane.layerLocalBounds(composition_id, layer_id)
        assert local_bounds == QRectF(0.0, 0.0, 100.0, 100.0)
        local_bounds.translate(500.0, 500.0)
        assert qpane.layerLocalBounds(composition_id, layer_id) == QRectF(
            0.0,
            0.0,
            100.0,
            100.0,
        )
        transform = QTransform(0.0, 1.0, -1.0, 0.0, 150.0, 5.0)

        assert qpane.setLayerTransform(composition_id, layer_id, transform)

        current = qpane.layerTransform(composition_id, layer_id)
        scene = qpane.currentScene()
        assert current is not None
        assert scene is not None
        assert current == transform
        assert scene.layers[0].transform == transform
        assert scene.layers[0].placement == QRectF(50.0, 5.0, 100.0, 100.0)
        current.translate(300.0, 300.0)
        assert qpane.layerTransform(composition_id, layer_id) == transform

        plan = qpane.view().calculateRenderPlan(is_blank=False)
        assert plan is not None
        item = plan.render_items[0]
        panel_point = item.transform.map(QPointF(25.0, 70.0)).toPoint()
        hit = qpane.sceneHitTest(panel_point)
        assert hit is not None
        assert hit.layer_id == layer_id
        assert hit.source_point.x() == pytest.approx(25.0, abs=1.0)
        assert hit.source_point.y() == pytest.approx(70.0, abs=1.0)
        expected_scene = transform.map(QPointF(25.0, 70.0))
        assert hit.scene_point.x() == pytest.approx(expected_scene.x(), abs=1.0)
        assert hit.scene_point.y() == pytest.approx(expected_scene.y(), abs=1.0)

        assert qpane.undoSceneEdit()
        assert qpane.layerTransform(composition_id, layer_id) == before
        assert qpane.redoSceneEdit()
        assert qpane.layerTransform(composition_id, layer_id) == transform
        with pytest.raises(ValueError, match="invertible"):
            qpane.setLayerTransform(
                composition_id,
                layer_id,
                QTransform(0.0, 0.0, 0.0, 1.0, 0.0, 0.0),
            )
        with pytest.raises(TypeError, match="scene_id"):
            qpane.layerLocalBounds("invalid", layer_id)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="layer_id"):
            qpane.layerLocalBounds(composition_id, "invalid")  # type: ignore[arg-type]
    finally:
        _cleanup_qpane(qpane, qapp)


def test_move_preview_preserves_rotated_linear_geometry(qapp) -> None:
    """Move gestures translate exact geometry without flattening its rotation."""
    qpane = CuteCanvas(features=())
    qpane.resize(160, 120)
    try:
        image_id, _second_id = _load_images(qpane)
        layer_id = uuid.uuid4()
        composition_id = qpane.composeScene(
            CompositionRequest(
                composition_id=None,
                title="Move rotated layer",
                bounds=QRectF(0.0, 0.0, 160.0, 120.0),
                layers=(
                    CatalogLayerRequest(
                        layer_id=layer_id,
                        image_id=image_id,
                        placement=QRectF(0.0, 0.0, 100.0, 100.0),
                        interaction=LayerPolicy(
                            selectable=True,
                            movable=True,
                        ),
                    ),
                ),
            )
        )
        rotated = QTransform(0.0, 1.0, -1.0, 0.0, 110.0, 0.0)
        assert qpane.setLayerTransform(composition_id, layer_id, rotated)
        qpane.show()
        qapp.processEvents()
        plan = qpane.view().calculateRenderPlan(is_blank=False)
        assert plan is not None
        origin = plan.render_items[0].transform.map(QPointF(50.0, 50.0))
        movement = qpane.sceneLayerMovementInteraction()

        candidate = movement.candidate_at(origin)
        assert candidate is not None
        assert movement.begin(candidate)
        assert movement.update(origin + QPointF(18.0, 9.0))
        preview = qpane.view().calculateRenderPlan(is_blank=False)
        assert preview is not None
        preview_transform = preview.render_items[0].descriptor.transform
        assert preview_transform is not None
        assert (
            preview_transform.m11,
            preview_transform.m12,
            preview_transform.m21,
            preview_transform.m22,
        ) == (0.0, 1.0, -1.0, 0.0)
        assert movement.finish(origin + QPointF(18.0, 9.0))
        committed = qpane.layerTransform(composition_id, layer_id)
        assert committed is not None
        assert (committed.m11(), committed.m12(), committed.m21(), committed.m22()) == (
            0.0,
            1.0,
            -1.0,
            0.0,
        )
    finally:
        _cleanup_qpane(qpane, qapp)


def test_space_pan_suspends_without_discarding_layer_transform_preview(qapp) -> None:
    """Temporary navigation must not cancel or commit unresolved layer geometry."""
    qpane = CuteCanvas(features=())
    qpane.resize(160, 120)
    try:
        image_id, _second_id = _load_images(qpane)
        layer_id = uuid.uuid4()
        composition_id = qpane.composeScene(
            CompositionRequest(
                composition_id=None,
                title="Suspended transform",
                bounds=QRectF(0.0, 0.0, 160.0, 120.0),
                layers=(
                    CatalogLayerRequest(
                        layer_id=layer_id,
                        image_id=image_id,
                        placement=QRectF(0.0, 0.0, 100.0, 100.0),
                        interaction=LayerPolicy(
                            selectable=True,
                            movable=True,
                        ),
                    ),
                ),
            )
        )
        rotated = QTransform(0.0, 1.0, -1.0, 0.0, 110.0, 0.0)
        assert qpane.setLayerTransform(composition_id, layer_id, rotated)
        qpane.setControlMode(qpane.CONTROL_MODE_MOVE)
        qpane.show()
        qapp.processEvents()
        plan = qpane.view().calculateRenderPlan(is_blank=False)
        assert plan is not None
        origin = plan.render_items[0].transform.map(QPointF(50.0, 50.0)).toPoint()
        destination = origin + QPoint(18, 9)

        QTest.mousePress(qpane, Qt.LeftButton, Qt.NoModifier, origin)
        QTest.mouseMove(qpane, destination, delay=0)
        qapp.processEvents()
        preview = qpane.view().current_scene_descriptor()
        assert preview is not None
        preview_transform = preview.layers[0].transform
        assert preview_transform is not None
        assert preview_transform != LayerTransform.from_qtransform(rotated)

        QTest.keyPress(qpane, Qt.Key_Space)
        qapp.processEvents()
        suspended = qpane.view().current_scene_descriptor()

        assert suspended is not None
        assert suspended.layers[0].transform == preview_transform
        assert qpane.layerTransform(composition_id, layer_id) == rotated
        QTest.keyRelease(qpane, Qt.Key_Space)
        assert qpane.getControlMode() == qpane.CONTROL_MODE_MOVE
        QTest.mouseRelease(qpane, Qt.LeftButton, Qt.NoModifier, destination)
        resumed_plan = qpane.view().calculateRenderPlan(is_blank=False)
        assert resumed_plan is not None
        resumed_origin = (
            resumed_plan.render_items[0].transform.map(QPointF(50.0, 50.0)).toPoint()
        )
        resumed_destination = resumed_origin + QPoint(8, 4)
        QTest.mousePress(qpane, Qt.LeftButton, Qt.NoModifier, resumed_origin)
        QTest.mouseMove(qpane, resumed_destination, delay=0)
        QTest.mouseRelease(
            qpane,
            Qt.LeftButton,
            Qt.NoModifier,
            resumed_destination,
        )
        qapp.processEvents()
        committed = qpane.layerTransform(composition_id, layer_id)
        assert committed is not None
        assert committed != rotated
        assert (committed.m11(), committed.m12(), committed.m21(), committed.m22()) == (
            rotated.m11(),
            rotated.m12(),
            rotated.m21(),
            rotated.m22(),
        )
        assert qpane.undoSceneEdit()
        assert qpane.layerTransform(composition_id, layer_id) == rotated
    finally:
        _cleanup_qpane(qpane, qapp)


def test_move_interaction_paints_transient_placement_before_commit(qapp) -> None:
    """Dragging should repaint moved scene pixels before durable placement changes."""
    qpane = CuteCanvas(features=())
    qpane.resize(100, 100)
    try:
        image_id = uuid.uuid4()
        qpane.setImagesByID(
            CuteCanvas.imageMapFromLists(
                [_solid_image(50, 50, Qt.red)],
                [None],
                [image_id],
            ),
            image_id,
        )
        layer_id = uuid.uuid4()
        qpane.composeScene(
            CompositionRequest(
                composition_id=None,
                title="Painted movement preview",
                bounds=QRectF(0.0, 0.0, 100.0, 100.0),
                layers=(
                    CatalogLayerRequest(
                        layer_id=layer_id,
                        image_id=image_id,
                        placement=QRectF(0.0, 0.0, 50.0, 50.0),
                        interaction=LayerPolicy(
                            selectable=True,
                            movable=True,
                        ),
                    ),
                ),
            )
        )
        qpane.show()
        qapp.processEvents()
        plan = qpane.view().calculateRenderPlan(is_blank=False)
        assert plan is not None
        item = plan.render_items[0]
        origin = item.transform.map(QPointF(25.0, 25.0))
        panel_delta = QPointF(25.0 * plan.zoom, 0.0)
        old_only = item.transform.map(QPointF(10.0, 25.0)).toPoint()
        new_only = (item.transform.map(QPointF(40.0, 25.0)) + panel_delta).toPoint()
        initial_frame = qpane.grab().toImage()
        assert initial_frame.pixelColor(old_only).red() > 200
        assert initial_frame.pixelColor(new_only).red() < 200

        movement = qpane.sceneLayerMovementInteraction()
        candidate = movement.candidate_at(origin)
        assert candidate is not None
        assert movement.begin(candidate)
        assert movement.update(origin + panel_delta)
        qapp.processEvents()
        preview_frame = qpane.grab().toImage()

        assert preview_frame.pixelColor(old_only).red() < 200
        assert preview_frame.pixelColor(new_only).red() > 200
        assert qpane.currentScene().layers[0].placement == QRectF(
            0.0,
            0.0,
            50.0,
            50.0,
        )
        assert movement.cancel()
    finally:
        _cleanup_qpane(qpane, qapp)


def test_generated_default_image_layer_uses_generic_movement_policy(qapp) -> None:
    """Default catalog layers should use the same policy and placement mutation path."""
    qpane = CuteCanvas(features=())
    try:
        _load_images(qpane)
        scene = qpane.currentScene()
        assert scene is not None
        layer = scene.layers[0]
        policy = LayerPolicy(selectable=True, movable=True)

        assert qpane.setLayerInteractionPolicy(scene.scene_id, layer.layer_id, policy)
        assert qpane.setLayerPlacement(
            scene.scene_id,
            layer.layer_id,
            QRectF(6.0, 4.0, layer.placement.width(), layer.placement.height()),
        )

        updated = qpane.currentScene()
        assert updated is not None
        assert updated.layers[0].interaction == policy
        assert updated.layers[0].placement.x() == pytest.approx(6.0)
        assert updated.layers[0].placement.y() == pytest.approx(4.0)
    finally:
        _cleanup_qpane(qpane, qapp)


def test_scene_hit_test_respects_clips(qapp) -> None:
    """Scene clips should constrain public hit testing."""
    qpane = CuteCanvas(features=())
    qpane.resize(100, 100)
    try:
        first_id, second_id = _load_images(qpane)
        request = CompositionRequest(
            composition_id=None,
            title=None,
            bounds=QRectF(0.0, 0.0, 100.0, 100.0),
            layers=(
                CatalogLayerRequest(
                    layer_id=uuid.uuid4(),
                    image_id=first_id,
                    placement=QRectF(0.0, 0.0, 100.0, 100.0),
                ),
                CatalogLayerRequest(
                    layer_id=uuid.uuid4(),
                    image_id=second_id,
                    placement=QRectF(0.0, 0.0, 100.0, 100.0),
                    clip=CompositionLayerClip(
                        coordinate_space="scene",
                        rect=QRectF(50.0, 0.0, 50.0, 100.0),
                    ),
                ),
            ),
        )
        qpane.composeScene(request)

        left_hit = qpane.sceneHitTest(QPoint(25, 50))
        right_hit = qpane.sceneHitTest(QPoint(75, 50))

        assert left_hit is not None
        assert right_hit is not None
        assert left_hit.image_id == first_id
        assert right_hit.image_id == second_id
    finally:
        _cleanup_qpane(qpane, qapp)


def test_large_public_scene_layers_use_tiles(qapp) -> None:
    """Large public scene layers should enter tiled rendering."""
    qpane = CuteCanvas(features=())
    qpane.resize(100, 100)
    try:
        first_id, second_id = _load_images(qpane, large=True)
        qpane.composeScene(
            CompositionRequest(
                composition_id=None,
                title=None,
                bounds=QRectF(0.0, 0.0, 2048.0, 1024.0),
                layers=(
                    CatalogLayerRequest(
                        layer_id=uuid.uuid4(),
                        image_id=first_id,
                        placement=QRectF(0.0, 0.0, 1024.0, 1024.0),
                    ),
                    CatalogLayerRequest(
                        layer_id=uuid.uuid4(),
                        image_id=second_id,
                        placement=QRectF(1024.0, 0.0, 1024.0, 1024.0),
                    ),
                ),
            )
        )
        qpane.setZoom1To1()

        plan = qpane.view().calculateRenderPlan(is_blank=False)

        assert plan is not None
        raster_items = [
            item
            for item in plan.render_items
            if isinstance(item, RasterLayerRenderItem)
        ]
        assert raster_items
        assert all(item.strategy == RenderStrategy.TILE for item in raster_items)
        assert all(item.visible_tile_range is not None for item in raster_items)
    finally:
        _cleanup_qpane(qpane, qapp)


def test_layered_scene_returns_to_default_compositions_after_catalog_changes(
    qapp,
) -> None:
    """Catalog removals and navigation should reopen normal composition snapshots."""
    qpane = CuteCanvas(features=())
    try:
        first_id, second_id = _load_images(qpane)
        cleared: list[object | None] = []
        qpane.sceneChanged.connect(cleared.append)
        layered_id = qpane.composeScene(_scene_request(first_id, second_id))

        qpane.removeImageByID(second_id)

        assert qpane.currentScene() is not None
        assert qpane.currentScene().composition_id != layered_id
        assert qpane.currentScene().layers[0].image_id == first_id
        assert cleared[-1] == qpane.currentScene()

        first_id, second_id = _load_images(qpane)
        layered_id = qpane.composeScene(_scene_request(first_id, second_id))
        qpane.setCurrentImageID(second_id)

        assert qpane.currentScene().composition_id != layered_id
        assert qpane.currentScene().layers[0].image_id == second_id
        assert qpane.currentImageID() == second_id
        assert cleared[-1] == qpane.currentScene()
    finally:
        _cleanup_qpane(qpane, qapp)


def test_scene_survives_catalog_replacement_with_same_ids(qapp) -> None:
    """Replacing catalog pixels with the same IDs should keep the scene active."""
    qpane = CuteCanvas(features=())
    try:
        first_id, second_id = _load_images(qpane)
        qpane.composeScene(_scene_request(first_id, second_id))

        qpane.addImage(second_id, _solid_image(color=Qt.yellow), None)

        assert qpane.currentScene() is not None
        plan = qpane.view().calculateRenderPlan(is_blank=False)
        assert plan is not None
        raster_items = [
            item
            for item in plan.render_items
            if isinstance(item, RasterLayerRenderItem)
        ]
        assert raster_items[1].pyramid_asset_key.source_id == second_id
    finally:
        _cleanup_qpane(qpane, qapp)


def test_public_scene_suppresses_comparison_contributions(qapp) -> None:
    """Public scenes should render their declared layers without comparison layers."""
    qpane = CuteCanvas(features=())
    try:
        first_id, second_id = _load_images(qpane)
        qpane.setComparisonImageID(second_id)
        qpane.composeScene(
            CompositionRequest(
                composition_id=None,
                title=None,
                bounds=QRectF(0.0, 0.0, 100.0, 100.0),
                layers=(
                    CatalogLayerRequest(
                        layer_id=uuid.uuid4(),
                        image_id=first_id,
                        placement=QRectF(0.0, 0.0, 100.0, 100.0),
                    ),
                ),
            )
        )

        plan = qpane.view().calculateRenderPlan(is_blank=False)

        assert plan is not None
        raster_items = [
            item
            for item in plan.render_items
            if isinstance(item, RasterLayerRenderItem)
        ]
        assert len(raster_items) == 1
        assert raster_items[0].descriptor.source.image_id == first_id
    finally:
        _cleanup_qpane(qpane, qapp)


def test_layered_scene_rejects_image_scoped_comparison_mutations(qapp) -> None:
    """Layered scenes should not mutate comparison state through stale image scope."""
    qpane = CuteCanvas(features=())
    try:
        first_id, second_id = _load_images(qpane)
        qpane.setComparisonSplit(0.25, ComparisonOrientation.HORIZONTAL)
        qpane.composeScene(_scene_request(first_id, second_id))

        with pytest.raises(RuntimeError):
            qpane.setComparisonImageID(second_id)
        with pytest.raises(RuntimeError):
            qpane.clearComparisonImage()
        with pytest.raises(RuntimeError):
            qpane.setComparisonSplit(0.75, ComparisonOrientation.VERTICAL)

        state = qpane.comparisonState()
        assert not state.enabled
        assert state.source_id is None
        assert state.split_position == 0.25
        assert state.orientation == ComparisonOrientation.HORIZONTAL
    finally:
        _cleanup_qpane(qpane, qapp)


def test_composition_masks_delegate_without_catalog_image_anchor(
    qapp, monkeypatch
) -> None:
    """Generic mask identity and editing must not depend on catalog navigation."""
    qpane = CuteCanvas(features=())
    try:
        first_id, second_id = _load_images(qpane)
        qpane.composeScene(_scene_request(first_id, second_id))
        controller = qpane._masks_controller
        mask_id = uuid.uuid4()
        delegated_calls = []

        monkeypatch.setattr(controller, "getActiveMaskID", lambda: mask_id)
        monkeypatch.setattr(
            controller,
            "maskIDsForImage",
            lambda image_id=None: delegated_calls.append(("maskIDs", image_id))
            or [mask_id],
        )
        monkeypatch.setattr(
            controller,
            "listMasksForImage",
            lambda image_id=None: delegated_calls.append(("listMasks", image_id))
            or ("mask-info",),
        )
        monkeypatch.setattr(
            controller,
            "get_active_mask_image",
            lambda: _solid_image(1, 1),
        )
        monkeypatch.setattr(
            controller,
            "get_mask_undo_state",
            lambda queried_id: delegated_calls.append(("undoState", queried_id)),
        )

        assert qpane.activeMaskID() == mask_id
        assert qpane.maskIDsForImage() == [mask_id]
        assert qpane.listMasksForImage() == ("mask-info",)
        assert not qpane.getActiveMaskImage().isNull()
        assert qpane.maskIDsForImage(first_id) == [mask_id]
        assert qpane.listMasksForImage(first_id) == ("mask-info",)
        assert qpane.getMaskUndoState(mask_id) is None
        assert delegated_calls == [
            ("maskIDs", None),
            ("listMasks", None),
            ("maskIDs", first_id),
            ("listMasks", first_id),
            ("undoState", mask_id),
        ]

        monkeypatch.setattr(
            controller,
            "set_active_mask_id",
            lambda selected_id: delegated_calls.append(("activate", selected_id))
            or True,
        )
        monkeypatch.setattr(
            controller,
            "cycle_masks_forward",
            lambda: delegated_calls.append(("cycle", "forward")) or True,
        )
        monkeypatch.setattr(
            controller,
            "cycle_masks_backward",
            lambda: delegated_calls.append(("cycle", "backward")) or True,
        )
        monkeypatch.setattr(
            controller,
            "undo_mask_edit",
            lambda: delegated_calls.append(("history", "undo")) or True,
        )
        monkeypatch.setattr(
            controller,
            "redo_mask_edit",
            lambda: delegated_calls.append(("history", "redo")) or True,
        )

        assert qpane.createBlankMask(QSize(1, 1)) is None
        assert qpane.loadMaskFromFile("mask.png") is None
        assert qpane.setActiveMaskID(mask_id)
        assert qpane.cycleMasksForward()
        assert qpane.cycleMasksBackward()
        assert qpane.undoMaskEdit()
        assert qpane.redoMaskEdit()
        assert delegated_calls[-5:] == [
            ("activate", mask_id),
            ("cycle", "forward"),
            ("cycle", "backward"),
            ("history", "undo"),
            ("history", "redo"),
        ]

        delegated_calls.clear()
        monkeypatch.setattr(
            controller,
            "remove_mask_from_image",
            lambda image_id, removed_id: delegated_calls.append(
                ("remove", image_id, removed_id)
            )
            or False,
        )
        monkeypatch.setattr(
            controller,
            "set_mask_properties",
            lambda edited_id, color=None, opacity=None: delegated_calls.append(
                ("properties", edited_id, color, opacity)
            )
            or False,
        )
        monkeypatch.setattr(
            controller,
            "prefetch_mask_overlays",
            lambda image_id, *, reason: delegated_calls.append(
                ("prefetch", image_id, reason)
            )
            or True,
        )

        assert not qpane.removeMaskFromImage(first_id, mask_id)
        assert not qpane.setMaskProperties(mask_id, opacity=0.5)
        assert qpane.prefetchMaskOverlays(first_id, reason="test")
        assert qpane.prefetchMaskOverlays(None, reason="test")
        assert delegated_calls == [
            ("remove", first_id, mask_id),
            ("properties", mask_id, None, 0.5),
            ("prefetch", first_id, "test"),
            ("prefetch", None, "test"),
        ]
    finally:
        _cleanup_qpane(qpane, qapp)


def test_scene_overlays_receive_layer_geometry(qapp) -> None:
    """Scene overlays should receive public layer snapshots with transforms."""
    qpane = CuteCanvas(features=())
    qpane.resize(200, 100)
    try:
        first_id, second_id = _load_images(qpane)
        request = _scene_request(first_id, second_id)
        qpane.composeScene(request)
        states = []

        def draw_scene_overlay(_painter, state) -> None:
            states.append(state)

        qpane.registerSceneOverlay("labels", draw_scene_overlay)
        qpane.paintEvent(None)

        assert states
        state = states[-1]
        assert state.scene_id == qpane.currentScene().scene_id
        assert [layer.layer_id for layer in state.layers] == [
            layer.layer_id for layer in request.layers
        ]
        assert [layer.source_id for layer in state.layers] == [first_id, second_id]
        assert state.layers[0].role == "thumbnail"
        assert state.layers[0].metadata == {"slot": 0}
        assert state.layers[0].placement == request.layers[0].placement
        assert state.layers[0].source_size == QSize(100, 100)
        assert state.layers[0].panel_bounds.width() > 0
        qpane.unregisterSceneOverlay("labels")
        assert qpane.sceneOverlays() == {}
    finally:
        _cleanup_qpane(qpane, qapp)
