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
"""Tests for transient-to-durable floating-pixel render handoff."""

from __future__ import annotations

import uuid
from dataclasses import replace

from PySide6.QtCore import QRect, QRectF, QSize
from PySide6.QtGui import QColor, QImage, QTransform

from qpane.rendering.transient_raster import TransientRasterHandoff
from qpane.scene.affine import LayerTransform
from qpane.scene.raster import RasterBounds
from qpane.scene.raster_sampling import RasterPresentationSampling
from qpane.scene.render_plan import (
    SampledLayerRenderItem,
    SampledTileRenderData,
    SceneRenderPlan,
    TransientRasterResolvedContribution,
    TransientRasterTransformContribution,
    TransientSampledResolvedContribution,
)
from qpane_test_support.render_plan import make_render_plan


def test_handoff_retains_resolved_pixels_until_durable_revision_advances() -> None:
    """A commit frame must retain exact transient pixels until its source updates."""
    plan = make_render_plan(QRect(0, 0, 64, 64))
    item = plan.render_items[0]
    resolved_image = QImage(64, 64, QImage.Format_ARGB32_Premultiplied)
    resolved_image.fill(QColor(20, 120, 220, 255))
    contribution = TransientRasterResolvedContribution(
        session_id=uuid.uuid4(),
        scene_id=item.descriptor.scene_id,
        layer_id=item.descriptor.layer_id,
        source_asset_key=item.asset_key,
        source_image=resolved_image,
        source_bounds=RasterBounds(0, 0, 64, 64),
    )
    handoff = TransientRasterHandoff()

    active, active_redraw = handoff.settled_plan(
        replace(plan, transient_raster=contribution)
    )
    waiting, waiting_redraw = handoff.settled_plan(plan)

    assert active.transient_raster is contribution
    assert not active_redraw
    assert waiting.transient_raster is contribution
    assert not waiting_redraw

    advanced_key = replace(
        item.asset_key,
        source_revision=item.asset_key.source_revision + 1,
    )
    refining_item = replace(item, asset_key=advanced_key)
    refining, refining_redraw = handoff.settled_plan(
        replace(plan, render_items=(refining_item,))
    )

    assert refining.transient_raster is contribution
    assert not refining_redraw

    converged_item = replace(
        item,
        source_image=resolved_image,
        asset_key=advanced_key,
    )
    converged, converged_redraw = handoff.settled_plan(
        replace(plan, render_items=(converged_item,))
    )

    assert converged.transient_raster is None
    assert converged_redraw


def test_handoff_yields_to_a_newer_durable_edit_when_products_cannot_match() -> None:
    """A superseding mutation must replace a retained settled presentation."""
    plan = make_render_plan(QRect(0, 0, 64, 64))
    item = plan.render_items[0]
    image = QImage(64, 64, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor(180, 40, 100, 255))
    contribution = TransientRasterResolvedContribution(
        session_id=uuid.uuid4(),
        scene_id=item.descriptor.scene_id,
        layer_id=item.descriptor.layer_id,
        source_asset_key=item.asset_key,
        source_image=image,
        source_bounds=RasterBounds(0, 0, 64, 64),
    )
    handoff = TransientRasterHandoff()
    handoff.settled_plan(replace(plan, transient_raster=contribution))
    first_revision = replace(
        item.asset_key,
        source_revision=item.asset_key.source_revision + 1,
    )
    waiting, waiting_redraw = handoff.settled_plan(
        replace(plan, render_items=(replace(item, asset_key=first_revision),))
    )
    assert waiting.transient_raster is contribution
    assert not waiting_redraw

    superseding_revision = replace(
        item.asset_key,
        source_revision=item.asset_key.source_revision + 2,
    )
    superseded, superseded_redraw = handoff.settled_plan(
        replace(plan, render_items=(replace(item, asset_key=superseding_revision),))
    )

    assert superseded.transient_raster is None
    assert superseded_redraw


def test_handoff_discards_pixels_when_the_source_layer_disappears() -> None:
    """Removed layers must not retain orphaned floating presentation."""
    plan = make_render_plan(QRect(0, 0, 64, 64))
    item = plan.render_items[0]
    image = QImage(64, 64, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor(200, 80, 20, 255))
    contribution = TransientRasterResolvedContribution(
        session_id=uuid.uuid4(),
        scene_id=item.descriptor.scene_id,
        layer_id=item.descriptor.layer_id,
        source_asset_key=item.asset_key,
        source_image=image,
        source_bounds=RasterBounds(0, 0, 64, 64),
    )
    handoff = TransientRasterHandoff()
    handoff.settled_plan(replace(plan, transient_raster=contribution))

    settled, needs_redraw = handoff.settled_plan(replace(plan, render_items=()))

    assert settled.transient_raster is None
    assert needs_redraw


def test_sampled_handoff_rejects_tiles_after_source_lattice_changes() -> None:
    """Settled sampled tiles must not be interpreted through tightened geometry."""

    plan = make_render_plan(QRect(0, 0, 64, 64))
    raster_item = plan.render_items[0]
    source_size = QSize(96, 64)
    preview_bounds = RasterBounds(-32, 0, 96, 64)
    descriptor = replace(raster_item.descriptor, raster_bounds=preview_bounds)
    tile_image = QImage(source_size, QImage.Format.Format_ARGB32_Premultiplied)
    tile_image.fill(QColor(220, 40, 120, 255))
    tile = SampledTileRenderData(
        tile_image,
        QRectF(0.0, 0.0, 96.0, 64.0),
        QRectF(tile_image.rect()),
    )
    sampled_item = SampledLayerRenderItem(
        descriptor=descriptor,
        transform=QTransform(),
        placement=descriptor.placement,
        clip=descriptor.clip,
        source_size=source_size,
        presentation_sampling=RasterPresentationSampling.NEAREST,
        tiles=(tile,),
    )
    contribution = TransientSampledResolvedContribution(
        session_id=uuid.uuid4(),
        scene_id=descriptor.scene_id,
        layer_id=descriptor.layer_id,
        source_asset_key=raster_item.asset_key,
        source_bounds=RasterBounds(-24, 8, 16, 16),
        tiles=(tile,),
        sampled_raster_bounds=preview_bounds,
        sampled_source_size=source_size,
    )
    handoff = TransientRasterHandoff()
    handoff.settled_plan(
        replace(
            plan,
            render_items=(sampled_item,),
            transient_raster=contribution,
        )
    )
    durable_bounds = RasterBounds(-16, 0, 80, 64)
    durable_descriptor = replace(descriptor, raster_bounds=durable_bounds)
    durable_item = replace(
        sampled_item,
        descriptor=durable_descriptor,
        source_size=QSize(80, 64),
    )

    settled, needs_redraw = handoff.settled_plan(
        replace(plan, render_items=(durable_item,))
    )

    assert settled.transient_raster is None
    assert needs_redraw


def test_sampled_handoff_rejects_an_active_product_from_another_demand() -> None:
    """A host cannot apply a sampled replacement to a different current batch."""
    plan, _item, contribution = _sampled_handoff_fixture()
    shifted_tile = replace(
        contribution.tiles[0],
        source_rect=QRectF(64.0, 0.0, 64.0, 64.0),
    )
    mismatched = replace(
        contribution,
        tiles=(shifted_tile,),
    )

    settled, needs_redraw = TransientRasterHandoff().settled_plan(
        replace(plan, transient_raster=mismatched)
    )

    assert settled.transient_raster is None
    assert needs_redraw


def test_sampled_handoff_retains_equal_coverage_across_tile_repartition() -> None:
    """Overview partition changes cannot displace exact held edit pixels."""
    plan, item, contribution = _sampled_handoff_fixture()
    first_image = QImage(32, 64, QImage.Format.Format_ARGB32_Premultiplied)
    second_image = QImage(32, 64, QImage.Format.Format_ARGB32_Premultiplied)
    first_image.fill(QColor(40, 80, 120, 255))
    second_image.fill(QColor(40, 80, 120, 255))
    partitioned = replace(
        item,
        tiles=(
            SampledTileRenderData(
                first_image,
                QRectF(0.0, 0.0, 32.0, 64.0),
                QRectF(first_image.rect()),
            ),
            SampledTileRenderData(
                second_image,
                QRectF(32.0, 0.0, 32.0, 64.0),
                QRectF(second_image.rect()),
            ),
        ),
    )

    settled, needs_redraw = TransientRasterHandoff().settled_plan(
        replace(
            plan,
            render_items=(partitioned,),
            transient_raster=contribution,
        )
    )

    assert settled.transient_raster is contribution
    assert not needs_redraw


def test_sampled_handoff_releases_after_the_committed_source_changes_again() -> None:
    """The committed presentation remains exact until a later source revision."""
    plan, item, contribution = _sampled_handoff_fixture()
    handoff = TransientRasterHandoff()
    handoff.settled_plan(replace(plan, transient_raster=contribution))
    waiting, waiting_redraw = handoff.settled_plan(plan)
    durable_descriptor = replace(
        item.descriptor,
        source_revision=item.descriptor.source_revision + 31,
    )
    different_image = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
    different_image.fill(QColor(20, 240, 80, 255))
    durable_tile = replace(item.tiles[0], image=different_image)
    durable_item = replace(
        item,
        descriptor=durable_descriptor,
        tiles=(durable_tile,),
    )

    durable, durable_redraw = handoff.settled_plan(
        replace(plan, render_items=(durable_item,))
    )
    later_descriptor = replace(
        durable_descriptor,
        source_revision=durable_descriptor.source_revision + 1,
    )
    later_item = replace(durable_item, descriptor=later_descriptor)
    later, later_redraw = handoff.settled_plan(
        replace(plan, render_items=(later_item,))
    )
    assert waiting.transient_raster is contribution
    assert not waiting_redraw
    assert durable.transient_raster is contribution
    assert not durable_redraw
    assert later.transient_raster is None
    assert later_redraw


def test_sampled_handoff_retains_a_bounded_patch_without_hiding_other_tiles() -> None:
    """A sparse transient patch must remain valid over a sampled source revision."""
    plan, item, sampled = _sampled_handoff_fixture()
    patch_image = QImage(8, 8, QImage.Format.Format_ARGB32_Premultiplied)
    patch_image.fill(QColor(240, 30, 80, 255))
    contribution = TransientRasterResolvedContribution(
        session_id=sampled.session_id,
        scene_id=sampled.scene_id,
        layer_id=sampled.layer_id,
        source_asset_key=sampled.source_asset_key,
        source_image=patch_image,
        source_bounds=RasterBounds(48, 48, 8, 8),
    )
    handoff = TransientRasterHandoff()
    active, active_redraw = handoff.settled_plan(
        replace(plan, transient_raster=contribution)
    )
    advanced_item = replace(
        item,
        descriptor=replace(
            item.descriptor,
            source_revision=item.descriptor.source_revision + 1,
        ),
    )
    waiting, waiting_redraw = handoff.settled_plan(
        replace(plan, render_items=(advanced_item,))
    )

    assert active.transient_raster is contribution
    assert not active_redraw
    assert waiting.transient_raster is contribution
    assert not waiting_redraw
    assert contribution.source_bounds == RasterBounds(48, 48, 8, 8)


def test_handoff_discards_a_cancelled_transform_preview_immediately() -> None:
    """Cancellation must not retain an unresolved pointer-motion contribution."""
    plan = make_render_plan(QRect(0, 0, 64, 64))
    item = plan.render_items[0]
    fragment = QImage(16, 16, QImage.Format_ARGB32_Premultiplied)
    fragment.fill(QColor(80, 180, 40, 255))
    contribution = TransientRasterTransformContribution(
        session_id=uuid.uuid4(),
        scene_id=item.descriptor.scene_id,
        layer_id=item.descriptor.layer_id,
        source_asset_key=item.asset_key,
        source_patch=None,
        source_bounds=RasterBounds(8, 8, 16, 16),
        fragment_image=fragment,
        fragment_bounds=RasterBounds(8, 8, 16, 16),
        destination_attenuation_mask=None,
        fragment_transform=LayerTransform(dx=12.0, dy=4.0),
        extent_clip_bounds=None,
    )
    handoff = TransientRasterHandoff()
    handoff.settled_plan(replace(plan, transient_raster=contribution))

    settled, needs_redraw = handoff.settled_plan(plan)

    assert settled.transient_raster is None
    assert needs_redraw


def test_handoff_discards_nonretained_resolved_preview_immediately() -> None:
    """In-flight resolved feedback must disappear without a durable revision."""
    plan = make_render_plan(QRect(0, 0, 64, 64))
    item = plan.render_items[0]
    image = QImage(16, 16, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor(220, 40, 140, 255))
    contribution = TransientRasterResolvedContribution(
        session_id=uuid.uuid4(),
        scene_id=item.descriptor.scene_id,
        layer_id=item.descriptor.layer_id,
        source_asset_key=item.asset_key,
        source_image=image,
        source_bounds=RasterBounds(8, 8, 16, 16),
        retain_until_durable=False,
    )
    handoff = TransientRasterHandoff()
    handoff.settled_plan(replace(plan, transient_raster=contribution))

    settled, needs_redraw = handoff.settled_plan(plan)

    assert settled.transient_raster is None
    assert needs_redraw


def _sampled_handoff_fixture() -> tuple[
    SceneRenderPlan,
    SampledLayerRenderItem,
    TransientSampledResolvedContribution,
]:
    """Return one current sampled plan and its exact retained replacement."""
    plan = make_render_plan(QRect(0, 0, 64, 64))
    raster_item = plan.render_items[0]
    bounds = RasterBounds(0, 0, 64, 64)
    descriptor = replace(raster_item.descriptor, raster_bounds=bounds)
    source_image = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
    source_image.fill(QColor(40, 80, 120, 255))
    source_tile = SampledTileRenderData(
        source_image,
        QRectF(0.0, 0.0, 64.0, 64.0),
        QRectF(0.0, 0.0, 64.0, 64.0),
    )
    item = SampledLayerRenderItem(
        descriptor=descriptor,
        transform=QTransform(),
        placement=descriptor.placement,
        clip=descriptor.clip,
        source_size=QSize(64, 64),
        presentation_sampling=RasterPresentationSampling.NEAREST,
        tiles=(source_tile,),
    )
    resolved_image = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
    resolved_image.fill(QColor(220, 40, 120, 255))
    resolved_tile = replace(source_tile, image=resolved_image)
    contribution = TransientSampledResolvedContribution(
        session_id=uuid.uuid4(),
        scene_id=descriptor.scene_id,
        layer_id=descriptor.layer_id,
        source_asset_key=raster_item.asset_key,
        source_bounds=RasterBounds(8, 8, 16, 16),
        tiles=(resolved_tile,),
        sampled_raster_bounds=bounds,
        sampled_source_size=item.source_size,
    )
    return replace(plan, render_items=(item,)), item, contribution
