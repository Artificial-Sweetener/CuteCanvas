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

"""Contracts for sampled-layer continuity across source transitions."""

from __future__ import annotations

import uuid
from dataclasses import replace

from PySide6.QtCore import QRect
from PySide6.QtGui import QImage, Qt, QTransform
from qpane.rendering.sampled_frame_continuity import SampledFrameContinuity
from qpane.rendering.sdk import RasterSource
from qpane.scene.raster import RasterBounds
from qpane.scene.raster_sampling import RasterPresentationSampling
from qpane.scene.render_plan import SampledLayerRenderItem, SceneRenderPlan
from qpane_test_support.render_plan import make_render_plan


def test_replaced_source_is_a_transition_even_when_revision_is_unchanged() -> None:
    """Replacing a source object must retain the last complete sampled frame."""
    plan = make_render_plan(QRect(0, 0, 32, 32))
    plan = _sampled_plan(plan)
    previous_descriptor = plan.render_items[0].descriptor
    replacement_image = QImage(32, 32, QImage.Format_ARGB32_Premultiplied)
    replacement_image.fill(Qt.black)
    replacement_source = RasterSource.from_image(
        replacement_image,
        source_id=uuid.uuid4(),
        revision=previous_descriptor.source_revision,
        source_kind="test-raster",
    )
    current_descriptor = replace(previous_descriptor, source=replacement_source)

    changed_layer_ids = SampledFrameContinuity().changed_layer_ids(
        (current_descriptor,),
        previous_plan=plan,
    )

    assert changed_layer_ids == frozenset({previous_descriptor.layer_id})


def test_new_revision_of_same_source_is_a_transition() -> None:
    """Advancing source content must retain the last complete sampled frame."""
    plan = make_render_plan(QRect(0, 0, 32, 32))
    plan = _sampled_plan(plan)
    previous_descriptor = plan.render_items[0].descriptor
    current_descriptor = replace(
        previous_descriptor,
        source_revision=previous_descriptor.source_revision + 1,
    )

    changed_layer_ids = SampledFrameContinuity().changed_layer_ids(
        (current_descriptor,),
        previous_plan=plan,
    )

    assert changed_layer_ids == frozenset({previous_descriptor.layer_id})


def test_raster_fallback_is_a_transition_to_sampled_presentation() -> None:
    """Returning from a dense fallback must retain it until sampling settles."""
    plan = make_render_plan(QRect(0, 0, 32, 32))
    current_descriptor = plan.render_items[0].descriptor

    changed_layer_ids = SampledFrameContinuity().changed_layer_ids(
        (current_descriptor,),
        previous_plan=plan,
    )

    assert changed_layer_ids == frozenset({current_descriptor.layer_id})


def test_changed_source_lattice_is_a_transition() -> None:
    """Expanded sampled bounds must retain the prior complete presentation."""
    plan = _sampled_plan(make_render_plan(QRect(0, 0, 32, 32)))
    previous_descriptor = plan.render_items[0].descriptor
    current_descriptor = replace(
        previous_descriptor,
        raster_bounds=RasterBounds(-8, 0, 40, 32),
    )

    changed_layer_ids = SampledFrameContinuity().changed_layer_ids(
        (current_descriptor,),
        previous_plan=plan,
    )

    assert changed_layer_ids == frozenset({current_descriptor.layer_id})


def test_unchanged_sampled_source_is_not_a_transition() -> None:
    """Projection-only refinement must not restore stale sampled geometry."""
    plan = _sampled_plan(make_render_plan(QRect(0, 0, 32, 32)))
    current_descriptor = plan.render_items[0].descriptor

    changed_layer_ids = SampledFrameContinuity().changed_layer_ids(
        (current_descriptor,),
        previous_plan=plan,
    )

    assert changed_layer_ids == frozenset()


def test_prior_sampled_items_fill_missing_current_layers_from_retired_frame() -> None:
    """Projection fallback can recover a layer omitted by an unsettled frame."""
    retired = _sampled_plan(make_render_plan(QRect(0, 0, 32, 32)))
    continuity = SampledFrameContinuity()
    continuity.retire(retired)
    incomplete = replace(retired, render_items=())

    items = continuity.prior_sampled_items(incomplete)

    assert items == {
        retired.render_items[0].descriptor.layer_id: retired.render_items[0]
    }


def _sampled_plan(plan: SceneRenderPlan) -> SceneRenderPlan:
    """Replace one test raster item with an equivalent sampled presentation."""
    raster_item = plan.render_items[0]
    descriptor = raster_item.descriptor
    return replace(
        plan,
        render_items=(
            SampledLayerRenderItem(
                descriptor=descriptor,
                transform=QTransform(),
                placement=descriptor.placement,
                clip=descriptor.clip,
                source_size=raster_item.source_image.size(),
                presentation_sampling=RasterPresentationSampling.NEAREST,
                tiles=(),
            ),
        ),
    )
