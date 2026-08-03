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
"""Tests for transient-to-durable floating-pixel render handoff."""

from __future__ import annotations

import uuid
from dataclasses import replace

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage
from qpane.rendering.transient_raster import TransientRasterHandoff
from qpane.scene.affine import LayerTransform
from qpane.scene.raster import RasterBounds
from qpane.scene.render_plan import (
    TransientRasterResolvedContribution,
    TransientRasterTransformContribution,
)

from tests.helpers.render_plan import make_render_plan


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


def test_handoff_discards_a_cancelled_transform_preview_immediately() -> None:
    """Cancellation must not retain an unresolved pointer-motion contribution."""
    plan = make_render_plan(QRect(0, 0, 64, 64))
    item = plan.render_items[0]
    fragment = QImage(16, 16, QImage.Format_ARGB32_Premultiplied)
    fragment.fill(QColor(80, 180, 40, 255))
    selection_mask = QImage(16, 16, QImage.Format_ARGB32_Premultiplied)
    selection_mask.fill(0xFF000000)
    contribution = TransientRasterTransformContribution(
        session_id=uuid.uuid4(),
        scene_id=item.descriptor.scene_id,
        layer_id=item.descriptor.layer_id,
        source_asset_key=item.asset_key,
        source_patch=None,
        source_bounds=RasterBounds(8, 8, 16, 16),
        fragment_image=fragment,
        fragment_bounds=RasterBounds(8, 8, 16, 16),
        selection_mask=selection_mask,
        fragment_transform=LayerTransform(dx=12.0, dy=4.0),
        clear_destination=False,
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
