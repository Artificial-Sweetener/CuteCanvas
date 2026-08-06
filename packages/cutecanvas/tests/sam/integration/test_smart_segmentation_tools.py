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
"""Characterize the two products sharing Smart segmentation gestures."""

from __future__ import annotations

import uuid

import numpy as np
from cutecanvas.coverage import CoverageCombineMode
from cutecanvas.cursor import EditorCursorIntent
from cutecanvas.resources import ProjectResourceReference
from cutecanvas.sam.segmentation_request import SmartSegmentationProduct
from cutecanvas.selection.service import PixelSelectionService
from cutecanvas.selection.smart_segmentation import SmartSelectionResultCommitter
from cutecanvas.tools.cursor_feedback import ToolCursorStyle
from cutecanvas.tools.ports import SmartSegmentationInteractionPort
from cutecanvas.tools.smart_segmentation import SmartMaskTool, SmartSelectTool
from qpane.scene.affine import LayerTransform
from qpane.scene.model import (
    LayerDescriptor,
    LayerKind,
    LayerPlacement,
    SceneDescriptor,
    SceneKind,
)
from qpane.scene.raster import RasterBounds


def test_smart_tools_share_selection_cursor_but_declare_distinct_products() -> None:
    """Both gestures use selection feedback while committing different products."""

    smart_select = SmartSelectTool()
    smart_mask = SmartMaskTool()

    assert smart_select.cursor_style is ToolCursorStyle.PRECISE
    assert smart_mask.cursor_style is ToolCursorStyle.PRECISE
    assert smart_select.cursor_intent() is EditorCursorIntent.PRECISE
    assert smart_mask.cursor_intent() is EditorCursorIntent.PRECISE
    assert SmartSelectTool.product is SmartSegmentationProduct.PIXEL_SELECTION
    assert SmartMaskTool.product is SmartSegmentationProduct.MASK_COVERAGE


def test_smart_tools_decorate_the_selection_cursor_for_coverage_modifiers() -> None:
    """Smart selection and mask gestures should expose add and subtract feedback."""

    for tool_type in (SmartSelectTool, SmartMaskTool):
        tool = tool_type()
        tool.activate(
            SmartSegmentationInteractionPort(
                is_alt_held=lambda: True,
                is_shift_held=lambda: True,
            )
        )
        assert tool.cursor_intent() is EditorCursorIntent.PRECISE_SUBTRACT

        tool.activate(
            SmartSegmentationInteractionPort(
                is_shift_held=lambda: True,
            )
        )
        assert tool.cursor_intent() is EditorCursorIntent.PRECISE_ADD


def test_smart_request_retains_target_and_selection_algebra() -> None:
    """Asynchronous inference must retain its exact product and document target."""
    request = SmartSelectTool.build_request(
        scene_id=uuid.uuid4(),
        layer_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        mask_id=None,
        bounds=(1.0, 2.0, 20.0, 30.0),
        combine_mode=CoverageCombineMode.SUBTRACT,
    )

    assert request.product is SmartSegmentationProduct.PIXEL_SELECTION
    assert request.mask_id is None
    assert request.combine_mode is CoverageCombineMode.SUBTRACT


def test_smart_selection_result_projects_into_captured_layer_scene() -> None:
    """Segmented source coverage follows the captured raster instance transform."""
    scene_id = uuid.uuid4()
    layer_id = uuid.uuid4()
    resource_id = uuid.uuid4()
    transform = LayerTransform(dx=11.0, dy=7.0)
    layer = LayerDescriptor(
        scene_id=scene_id,
        layer_id=layer_id,
        kind=LayerKind.RASTER,
        source=ProjectResourceReference(resource_id),
        placement=transform.map_bounds(RasterBounds(0, 0, 3, 2)),
        raster_bounds=RasterBounds(0, 0, 3, 2),
        transform=transform,
    )
    scene = SceneDescriptor(
        scene_id,
        SceneKind.EXPLICIT,
        LayerPlacement(0.0, 0.0, 32.0, 32.0),
        (layer,),
    )
    selections = PixelSelectionService()
    committer = SmartSelectionResultCommitter(
        active_scene=lambda: scene,
        selections=selections,
    )
    request = SmartSelectTool.build_request(
        scene_id=scene_id,
        layer_id=layer_id,
        resource_id=resource_id,
        mask_id=None,
        bounds=(0.0, 0.0, 3.0, 2.0),
        combine_mode=CoverageCombineMode.REPLACE,
    )

    assert committer.commit(
        request,
        np.array([[0, 255, 0], [0, 0, 0]], dtype=np.uint8),
    )
    coverage = selections.state(scene_id).coverage
    assert coverage is not None
    assert coverage.bounds == RasterBounds(12, 7, 1, 1)


def test_smart_selection_result_rejects_a_stale_scene_target() -> None:
    """Late inference cannot write into a different active document."""
    selections = PixelSelectionService()
    committer = SmartSelectionResultCommitter(
        active_scene=lambda: None,
        selections=selections,
    )
    request = SmartSelectTool.build_request(
        scene_id=uuid.uuid4(),
        layer_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        mask_id=None,
        bounds=(0.0, 0.0, 2.0, 2.0),
        combine_mode=CoverageCombineMode.REPLACE,
    )

    assert not committer.commit(request, np.full((2, 2), 255, dtype=np.uint8))
    assert selections.state(request.scene_id).coverage is None
