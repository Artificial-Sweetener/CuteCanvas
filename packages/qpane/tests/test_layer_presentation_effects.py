#    QPane - High-performance PySide6 image viewer
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

"""Public lifecycle and pixel contracts for transient layer effects."""

from __future__ import annotations

import uuid
from dataclasses import replace

import pytest
from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPicture, QTransform
from qpane.rendering.item_compositor import SceneItemCompositor
from qpane.rendering.presentation_effect_compositor import (
    LayerPresentationEffectCompositor,
)
from qpane.scene.affine import LayerTransform
from qpane.scene.model import ClipCoordinateSpace, LayerClip, LayerKind
from qpane.scene.raster import RasterBounds
from qpane.scene.render_plan import (
    SampledLayerRenderItem,
    SampledTileRenderData,
    TransientRasterTransformContribution,
    VectorLayerRenderItem,
)

from qpane import (
    LayerPresentationEffect,
    LayerPresentationStyle,
    QPane,
    RasterSource,
    RenderLayer,
    RenderScene,
)
from tests.harness.timing import interaction_clock, stable_latency_samples
from tests.helpers.render_plan import make_render_plan


def _sparse_image() -> QImage:
    """Return transparent storage containing one opaque content square."""
    image = QImage(20, 20, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        painter.fillRect(QRect(5, 6, 6, 5), QColor(40, 100, 180, 255))
    finally:
        painter.end()
    return image


def _draw_plan(plan, *, clip: QRect | None = None) -> QImage:
    """Draw one plan through QPane's authoritative scene compositor."""
    image = QImage(plan.qpane_rect.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        if clip is not None:
            painter.setClipRect(clip)
        SceneItemCompositor().draw_visible_items(painter, plan)
    finally:
        painter.end()
    return image


def test_public_effect_lifecycle_is_ordered_and_scene_scoped(qapp) -> None:
    """Hosts can add, update, remove, and automatically retire stale effects."""
    pane = QPane()
    try:
        source = RasterSource.from_image(_sparse_image())
        first = RenderLayer(source)
        second = RenderLayer(source)
        scene = RenderScene.from_size(QSize(20, 20), (first, second))
        assert pane.setScene(scene)

        first_id = pane.addLayerPresentationEffect(
            scene.scene_id,
            first.layer_id,
            LayerPresentationStyle.tint(QColor("red"), opacity=0.4),
        )
        second_id = pane.addLayerPresentationEffect(
            scene.scene_id,
            second.layer_id,
            LayerPresentationStyle.outline(QColor("white"), width=2.0),
        )
        assert tuple(
            effect.effect_id for effect in pane.layerPresentationEffects()
        ) == (first_id, second_id)

        replacement = LayerPresentationStyle.glow(QColor("cyan"), radius=5.0)
        assert pane.updateLayerPresentationEffect(first_id, replacement)
        assert pane.layerPresentationEffects()[0].style == replacement
        assert pane.removeLayerPresentationEffect(second_id)
        assert not pane.removeLayerPresentationEffect(second_id)

        with pytest.raises(ValueError, match="layer_id"):
            pane.addLayerPresentationEffect(
                scene.scene_id,
                uuid.uuid4(),
                replacement,
            )

        next_scene = RenderScene.from_size(QSize(20, 20), (RenderLayer(source),))
        assert pane.setScene(next_scene)
        assert pane.calculateRenderPlan() is not None
        assert pane.layerPresentationEffects() == ()
    finally:
        pane.close()
        pane.deleteLater()
        qapp.processEvents()


def test_content_tint_follows_alpha_instead_of_layer_storage() -> None:
    """Tint affects actual visible pixels and leaves transparent storage untouched."""
    plan = make_render_plan(QRect(0, 0, 20, 20), source_image=_sparse_image())
    layer = plan.render_items[0].descriptor
    effect = LayerPresentationEffect(
        plan.scene_id,
        layer.layer_id,
        LayerPresentationStyle.tint(QColor(240, 30, 20), opacity=1.0),
    )

    rendered = _draw_plan(replace(plan, presentation_effects=(effect,)))

    assert rendered.pixelColor(7, 8) == QColor(240, 30, 20, 255)
    assert rendered.pixelColor(2, 2).alpha() == 0


def test_content_outline_traces_outer_alpha_boundary() -> None:
    """Outline appears beside opaque content without filling transparent storage."""
    plan = make_render_plan(QRect(0, 0, 20, 20), source_image=_sparse_image())
    layer = plan.render_items[0].descriptor
    effect = LayerPresentationEffect(
        plan.scene_id,
        layer.layer_id,
        LayerPresentationStyle.outline(QColor(255, 220, 30), width=1.0),
    )

    rendered = _draw_plan(replace(plan, presentation_effects=(effect,)))

    assert rendered.pixelColor(4, 8) == QColor(255, 220, 30, 255)
    assert rendered.pixelColor(5, 8) == QColor(40, 100, 180, 255)
    assert rendered.pixelColor(1, 1).alpha() == 0


def test_content_outline_follows_transformed_and_clipped_visible_pixels() -> None:
    """Coverage effects share layer transforms and clips with normal rendering."""
    transform = QTransform.fromTranslate(7.0, 3.0)
    plan = make_render_plan(
        QRect(0, 0, 32, 24),
        source_image=_sparse_image(),
        transform=transform,
    )
    item = plan.render_items[0]
    clip = LayerClip(ClipCoordinateSpace.VIEWPORT, 13.0, 0.0, 3.0, 24.0)
    item = replace(item, descriptor=replace(item.descriptor, clip=clip), clip=clip)
    effect = LayerPresentationEffect(
        plan.scene_id,
        item.descriptor.layer_id,
        LayerPresentationStyle.outline(QColor("yellow"), width=1.0),
    )

    rendered = _draw_plan(
        replace(plan, render_items=(item,), presentation_effects=(effect,))
    )

    assert rendered.pixelColor(12, 10) == QColor("yellow")
    assert rendered.pixelColor(13, 10) == QColor(40, 100, 180, 255)
    assert rendered.pixelColor(16, 10) == QColor("yellow")
    assert rendered.pixelColor(11, 10).alpha() == 0


def test_content_outline_follows_rotated_alpha_geometry() -> None:
    """Coverage derives from the rendered affine result rather than source bounds."""
    transform = QTransform()
    transform.translate(20.0, 0.0)
    transform.rotate(90.0)
    plan = make_render_plan(
        QRect(0, 0, 30, 24),
        source_image=_sparse_image(),
        transform=transform,
    )
    item = plan.render_items[0]
    effect = LayerPresentationEffect(
        plan.scene_id,
        item.descriptor.layer_id,
        LayerPresentationStyle.outline(QColor("yellow"), width=1.0),
    )

    rendered = _draw_plan(replace(plan, presentation_effects=(effect,)))

    assert rendered.pixelColor(8, 7) == QColor("yellow")
    assert rendered.pixelColor(10, 7) == QColor(40, 100, 180, 255)
    assert rendered.pixelColor(6, 7).alpha() == 0


def test_content_effect_tracks_transient_raster_move_preview() -> None:
    """Effects follow the exact transient pixels shown during an editor move."""
    plan = make_render_plan(QRect(0, 0, 32, 24), source_image=_sparse_image())
    item = plan.render_items[0]
    source_patch = QImage(6, 5, QImage.Format.Format_ARGB32_Premultiplied)
    source_patch.fill(Qt.GlobalColor.transparent)
    fragment = QImage(6, 5, QImage.Format.Format_ARGB32_Premultiplied)
    fragment.fill(QColor(40, 100, 180, 255))
    selection = QImage(6, 5, QImage.Format.Format_ARGB32_Premultiplied)
    selection.fill(Qt.GlobalColor.black)
    contribution = TransientRasterTransformContribution(
        session_id=uuid.uuid4(),
        scene_id=plan.scene_id,
        layer_id=item.descriptor.layer_id,
        source_asset_key=item.asset_key,
        source_patch=source_patch,
        source_bounds=RasterBounds(5, 6, 6, 5),
        fragment_image=fragment,
        fragment_bounds=RasterBounds(5, 6, 6, 5),
        selection_mask=selection,
        fragment_transform=LayerTransform(dx=10.0, dy=0.0),
        clear_destination=False,
        extent_clip_bounds=None,
    )
    effect = LayerPresentationEffect(
        plan.scene_id,
        item.descriptor.layer_id,
        LayerPresentationStyle.outline(QColor("cyan"), width=1.0),
    )

    rendered = _draw_plan(
        replace(
            plan,
            transient_raster=contribution,
            presentation_effects=(effect,),
        )
    )

    assert rendered.pixelColor(14, 8) == QColor("cyan")
    assert rendered.pixelColor(15, 8) == QColor(40, 100, 180, 255)
    assert rendered.pixelColor(4, 8).alpha() == 0


def test_partial_effect_redraw_limits_the_intermediate_product() -> None:
    """Dirty-region repair must not rasterize a viewport-sized effect product."""
    source = QImage(1024, 768, QImage.Format.Format_ARGB32_Premultiplied)
    source.fill(QColor("white"))
    plan = make_render_plan(QRect(0, 0, 1024, 768), source_image=source)
    item = plan.render_items[0]
    effect = LayerPresentationEffect(
        plan.scene_id,
        item.descriptor.layer_id,
        LayerPresentationStyle.outline(QColor("cyan"), width=2.0),
    )
    plan = replace(plan, presentation_effects=(effect,))
    target = QImage(1024, 768, QImage.Format.Format_ARGB32_Premultiplied)
    target.fill(Qt.GlobalColor.transparent)
    item_compositor = SceneItemCompositor()
    intermediate_sizes: list[QSize] = []

    def draw_items(painter, render_plan, items) -> None:
        intermediate_sizes.append(QSize(painter.device().size()))
        item_compositor.draw_layer_items(painter, render_plan, items)

    painter = QPainter(target)
    try:
        painter.setClipRect(QRect(300, 200, 12, 9))
        LayerPresentationEffectCompositor().draw(
            painter,
            plan,
            draw_layer_items=draw_items,
            item_bounds=item_compositor.item_panel_bounds,
        )
    finally:
        painter.end()

    assert intermediate_sizes
    assert intermediate_sizes[0].width() <= 24
    assert intermediate_sizes[0].height() <= 21


def test_vector_effect_remains_stable_when_refined_tiles_replace_picture() -> None:
    """Immediate and refined vector products produce the same effect silhouette."""
    plan = make_render_plan(QRect(0, 0, 20, 20), source_image=_sparse_image())
    raster_item = plan.render_items[0]
    picture = QPicture()
    picture_painter = QPainter(picture)
    try:
        picture_painter.fillRect(QRect(5, 6, 6, 5), QColor(40, 100, 180, 255))
    finally:
        picture_painter.end()
    vector_item = VectorLayerRenderItem(
        descriptor=replace(raster_item.descriptor, kind=LayerKind.VECTOR),
        picture=picture,
        transform=QTransform(),
        placement=raster_item.placement,
        clip=None,
        source_size=QSize(20, 20),
        render_hint_enabled=True,
    )
    effect = LayerPresentationEffect(
        plan.scene_id,
        vector_item.descriptor.layer_id,
        LayerPresentationStyle.outline(QColor("yellow"), width=1.0),
    )
    immediate = _draw_plan(
        replace(
            plan,
            render_items=(vector_item,),
            presentation_effects=(effect,),
        )
    )
    refined_image = QImage(6, 5, QImage.Format.Format_ARGB32_Premultiplied)
    refined_image.fill(QColor(40, 100, 180, 255))
    refined = replace(
        vector_item,
        refined_tiles=(
            SampledTileRenderData(
                refined_image,
                QRectF(5.0, 6.0, 6.0, 5.0),
                QRectF(refined_image.rect()),
            ),
        ),
    )
    refined_frame = _draw_plan(
        replace(
            plan,
            render_items=(refined,),
            presentation_effects=(effect,),
        )
    )

    assert immediate.pixelColor(4, 8) == QColor("yellow")
    assert refined_frame.pixelColor(4, 8) == QColor("yellow")
    assert immediate.pixelColor(7, 8) == refined_frame.pixelColor(7, 8)


def test_sampled_source_effect_uses_the_resolved_tile_alpha() -> None:
    """Resolution-dependent sources need no source-domain effect implementation."""
    plan = make_render_plan(QRect(0, 0, 20, 20), source_image=_sparse_image())
    raster_item = plan.render_items[0]
    sample = QImage(6, 5, QImage.Format.Format_ARGB32_Premultiplied)
    sample.fill(QColor(40, 100, 180, 255))
    sampled_item = SampledLayerRenderItem(
        descriptor=replace(raster_item.descriptor, kind=LayerKind.HYBRID),
        transform=QTransform(),
        placement=raster_item.placement,
        clip=None,
        source_size=QSize(20, 20),
        render_hint_enabled=True,
        tiles=(
            SampledTileRenderData(
                sample,
                QRectF(5.0, 6.0, 6.0, 5.0),
                QRectF(sample.rect()),
            ),
        ),
    )
    effect = LayerPresentationEffect(
        plan.scene_id,
        sampled_item.descriptor.layer_id,
        LayerPresentationStyle.tint(QColor("magenta")),
    )

    rendered = _draw_plan(
        replace(
            plan,
            render_items=(sampled_item,),
            presentation_effects=(effect,),
        )
    )

    assert rendered.pixelColor(7, 8) == QColor("magenta")
    assert rendered.pixelColor(2, 2).alpha() == 0


def test_ordered_effects_compose_and_hidden_layers_emit_nothing() -> None:
    """Registration order is deterministic and visibility remains authoritative."""
    plan = make_render_plan(QRect(0, 0, 20, 20), source_image=_sparse_image())
    item = plan.render_items[0]
    effects = (
        LayerPresentationEffect(
            plan.scene_id,
            item.descriptor.layer_id,
            LayerPresentationStyle.tint(QColor("red")),
        ),
        LayerPresentationEffect(
            plan.scene_id,
            item.descriptor.layer_id,
            LayerPresentationStyle.tint(QColor("blue")),
        ),
    )

    visible = _draw_plan(replace(plan, presentation_effects=effects))
    hidden_item = replace(
        item,
        descriptor=replace(item.descriptor, visible=False),
    )
    hidden = _draw_plan(
        replace(plan, render_items=(hidden_item,), presentation_effects=effects)
    )

    assert visible.pixelColor(7, 8) == QColor("blue")
    assert hidden.pixelColor(7, 8).alpha() == 0


@pytest.mark.parametrize(
    ("factory", "message"),
    (
        (lambda: LayerPresentationStyle.tint(QColor(), opacity=0.5), "color"),
        (
            lambda: LayerPresentationStyle.tint(QColor("red"), opacity=1.1),
            "opacity",
        ),
        (
            lambda: LayerPresentationStyle.outline(QColor("red"), width=0.0),
            "positive width",
        ),
        (
            lambda: LayerPresentationStyle.glow(QColor("red"), radius=0.0),
            "positive radius",
        ),
    ),
)
def test_presentation_styles_reject_invalid_frame_work(factory, message: str) -> None:
    """Invalid or unbounded public styles fail before reaching the frame loop."""
    with pytest.raises(ValueError, match=message):
        factory()


def test_mounted_effect_pan_storm_stays_responsive(qapp) -> None:
    """Derived coverage remains interactive during sustained viewport motion."""
    source = QImage(1000, 800, QImage.Format.Format_ARGB32_Premultiplied)
    source.fill(Qt.GlobalColor.transparent)
    source_painter = QPainter(source)
    try:
        source_painter.fillRect(QRect(120, 100, 740, 560), QColor("white"))
    finally:
        source_painter.end()
    layer = RenderLayer(RasterSource.from_image(source))
    scene = RenderScene.from_size(source.size(), (layer,))
    pane = QPane()
    pane.resize(800, 600)
    try:
        assert pane.setScene(scene, fit=False)
        pane.addLayerPresentationEffect(
            scene.scene_id,
            layer.layer_id,
            LayerPresentationStyle.outline(QColor(40, 220, 255), width=2.0),
        )
        pane.show()
        qapp.processEvents()
        latencies: list[float] = []
        for index in range(96):
            started = interaction_clock()
            pane.setPan(
                QPointF(
                    float((index * 19) % 141 - 70),
                    float((index * 13) % 101 - 50),
                )
            )
            qapp.processEvents()
            latencies.append((interaction_clock() - started) * 1000.0)

        stable = stable_latency_samples(latencies, parallel_batch_size=12)
        assert max(stable) < 16.0
    finally:
        pane.clear()
        pane.close()
        pane.deleteLater()
        qapp.processEvents()


def test_effect_lifecycle_storm_is_bounded(qapp) -> None:
    """Pointer-hover style replacement must stay cheap and retain no stale effects."""
    pane = QPane()
    source = RasterSource.from_image(_sparse_image())
    layer = RenderLayer(source)
    scene = RenderScene.from_size(QSize(20, 20), (layer,))
    try:
        assert pane.setScene(scene)
        pane.resize(100, 100)
        pane.show()
        qapp.processEvents()
        started = interaction_clock()
        for index in range(500):
            effect_id = pane.addLayerPresentationEffect(
                scene.scene_id,
                layer.layer_id,
                LayerPresentationStyle.tint(
                    QColor(index % 255, 120, 220),
                    opacity=0.25,
                ),
            )
            assert pane.removeLayerPresentationEffect(effect_id)
        elapsed_ms = (interaction_clock() - started) * 1000.0

        assert elapsed_ms < 50.0
        assert pane.layerPresentationEffects() == ()
    finally:
        pane.close()
        pane.deleteLater()
        qapp.processEvents()
