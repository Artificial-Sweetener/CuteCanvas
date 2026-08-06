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
"""Contracts for document-owned canvas geometry workflows."""

from __future__ import annotations

import uuid

import numpy as np
from cutecanvas import CanvasAnchor, CanvasDocument, CanvasResamplingMode
from cutecanvas.composition.layers import CompositionLayerInstance
from cutecanvas.coverage import CoverageSnapshot
from cutecanvas.coverage.document import VectorCoverageItem
from cutecanvas.coverage.geometry import CoverageGeometryFactory
from cutecanvas.document.canvas_crop import CanvasCropEffect
from cutecanvas.resources import ProjectResourceReference
from cutecanvas.types import RasterExtentPolicy
from cutecanvas.vector.effects import VectorMaskEffect
from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QColor, QImage
from qpane.sdk.scene import LayerTransform, RasterBounds


def test_bounds_resize_anchors_content_without_resampling() -> None:
    """Keep source pixels exact while the bottom-right anchor moves content."""
    document = CanvasDocument()
    composition_id = document.create_composition_from_image(
        _image(QSize(4, 3), QColor("magenta"))
    )
    before_image = document.embedded_image_for_composition(composition_id)
    layer = document.resources.compositions.layers.layers_for_composition(
        composition_id
    )[0]

    assert document.resize_canvas_bounds(
        composition_id,
        QSize(8, 7),
        anchor=CanvasAnchor.BOTTOM_RIGHT,
    )

    state = document.snapshot().compositions[composition_id]
    assert state.scene_bounds is not None
    assert state.scene_bounds.size().toSize() == QSize(8, 7)
    moved = document.resources.compositions.layers.layer(
        composition_id,
        layer.layer_id,
    )
    assert moved is not None
    assert moved.transform == LayerTransform(dx=4.0, dy=4.0)
    assert document.embedded_image_for_composition(composition_id) == before_image


def test_center_anchor_uses_reversible_integer_bias_for_odd_deltas() -> None:
    """Avoid half-pixel translations when centered dimensions differ by one."""
    document = CanvasDocument()
    composition_id = document.create_composition_from_image(
        _image(QSize(4, 4), QColor("cyan"))
    )
    layer_id = document.resources.compositions.layers.layers_for_composition(
        composition_id
    )[0].layer_id

    assert document.resize_canvas_bounds(
        composition_id,
        QSize(5, 5),
        anchor=CanvasAnchor.CENTER,
    )
    grown = document.resources.compositions.layers.layer(composition_id, layer_id)
    assert grown is not None
    assert grown.transform == LayerTransform()

    assert document.resize_canvas_bounds(
        composition_id,
        QSize(4, 4),
        anchor=CanvasAnchor.CENTER,
    )
    restored = document.resources.compositions.layers.layer(composition_id, layer_id)
    assert restored is not None
    assert restored.transform == LayerTransform()


def test_bounds_resize_is_one_exact_undoable_document_edit() -> None:
    """Restore bounds and every layer transform through one chronology step."""
    document = CanvasDocument()
    composition_id = document.create_composition_from_image(
        _image(QSize(4, 3), QColor("yellow"))
    )

    assert document.resize_canvas_bounds(
        composition_id,
        QSize(9, 8),
        anchor=CanvasAnchor.RIGHT,
    )
    assert document.resources.compositions.edit_controller.undo(composition_id)
    restored = document.snapshot().compositions[composition_id]
    assert restored.scene_bounds is not None
    assert restored.scene_bounds.size().toSize() == QSize(4, 3)
    layer = document.resources.compositions.layers.layers_for_composition(
        composition_id
    )[0]
    assert layer.transform == LayerTransform()
    assert document.resources.compositions.edit_controller.redo(composition_id)
    resized = document.snapshot().compositions[composition_id]
    assert resized.scene_bounds is not None
    assert resized.scene_bounds.size().toSize() == QSize(9, 8)


def test_geometry_history_preserves_retained_and_evaluated_selection() -> None:
    """Translate selection authorship and pixels without ambiguous array equality."""
    document = CanvasDocument()
    composition_id = document.create_composition(QRectF(0.0, 0.0, 4.0, 4.0))
    selection = CoverageSnapshot(
        RasterBounds(1, 1, 2, 2),
        RasterExtentPolicy.FIXED,
        np.full((2, 2), 255, dtype=np.uint8),
    )
    assert document.resources.pixel_selection.commit(composition_id, selection)

    assert document.resize_canvas_bounds(
        composition_id,
        QSize(8, 8),
        anchor=CanvasAnchor.BOTTOM_RIGHT,
    )
    moved = document.resources.pixel_selection.state(composition_id).coverage
    assert moved is not None
    assert moved.bounds == RasterBounds(5, 5, 2, 2)
    assert document.resources.compositions.edit_controller.undo(composition_id)
    restored = document.resources.pixel_selection.state(composition_id).coverage
    assert restored is not None
    assert restored.bounds == selection.bounds
    assert np.array_equal(restored.pixels, selection.pixels)

    plan = document._canvas_resampling_owner.capture(
        composition_id,
        QSize(8, 8),
        mode=CanvasResamplingMode.FAST,
    )
    assert plan.estimated_retained_bytes >= selection.pixels.nbytes + 16
    assert document._canvas_resampling_owner.commit(
        document._canvas_resampling_owner.build(plan)
    )
    scaled = document.resources.pixel_selection.state(composition_id).coverage
    assert scaled is not None
    assert scaled.bounds == RasterBounds(2, 2, 4, 4)
    assert document.resources.compositions.edit_controller.undo(composition_id)
    restored_again = document.resources.pixel_selection.state(composition_id).coverage
    assert restored_again is not None
    assert restored_again.bounds == selection.bounds
    assert np.array_equal(restored_again.pixels, selection.pixels)


def test_resampling_replaces_raster_copy_on_write_with_exact_history() -> None:
    """Adopt resized pixels once while undo and redo retain both resources."""
    image = QImage(2, 2, QImage.Format.Format_ARGB32_Premultiplied)
    image.setPixelColor(0, 0, QColor("red"))
    image.setPixelColor(1, 0, QColor("green"))
    image.setPixelColor(0, 1, QColor("blue"))
    image.setPixelColor(1, 1, QColor("white"))
    document = CanvasDocument()
    composition_id = document.create_composition_from_image(image)
    before_layer = document.resources.compositions.layers.layers_for_composition(
        composition_id
    )[0]

    plan = document._canvas_resampling_owner.capture(
        composition_id,
        QSize(4, 6),
        mode=CanvasResamplingMode.FAST,
    )
    assert document._canvas_resampling_owner.commit(
        document._canvas_resampling_owner.build(plan)
    )

    after_layer = document.resources.compositions.layers.layers_for_composition(
        composition_id
    )[0]
    assert after_layer.source != before_layer.source
    resized = document.embedded_image_for_composition(composition_id)
    assert resized.size() == QSize(4, 6)
    assert resized.pixelColor(0, 0) == QColor("red")
    assert resized.pixelColor(3, 0) == QColor("green")
    assert resized.pixelColor(0, 5) == QColor("blue")
    assert resized.pixelColor(3, 5) == QColor("white")
    assert document.resources.compositions.edit_controller.undo(composition_id)
    assert document.embedded_image_for_composition(composition_id) == image
    assert document.resources.compositions.edit_controller.redo(composition_id)
    assert document.embedded_image_for_composition(composition_id) == resized


def test_resampling_rejects_a_product_after_document_state_changes() -> None:
    """Never install a worker product captured from stale canvas geometry."""
    document = CanvasDocument()
    composition_id = document.create_composition_from_image(
        _image(QSize(4, 4), QColor("cyan"))
    )
    plan = document._canvas_resampling_owner.capture(
        composition_id,
        QSize(8, 8),
        mode=CanvasResamplingMode.SMOOTH,
    )
    product = document._canvas_resampling_owner.build(plan)
    assert document.resize_canvas_bounds(
        composition_id,
        QSize(5, 5),
        anchor=CanvasAnchor.TOP_LEFT,
    )

    assert not document._canvas_resampling_owner.commit(product)
    assert all(
        document.resources.resources.get(item.target_id) is None
        for item in plan.resources
    )


def test_resampling_preserves_hybrid_mask_authorship() -> None:
    """Scale mask raster authority and retained vector geometry independently."""
    document = CanvasDocument()
    composition_id = document.create_composition(QRectF(0.0, 0.0, 2.0, 2.0))
    mask_image = _image(QSize(2, 2), QColor("white"))
    mask_id = document.masks.create_mask_from_image(mask_image)
    mask = document.masks.get_layer(mask_id)
    assert mask is not None
    retained = VectorCoverageItem(
        uuid.uuid4(),
        CoverageGeometryFactory().rectangle(QRectF(0.0, 0.0, 1.0, 1.0)),
    )
    mask.coverage.append(retained)
    assert document.resources.compositions.layers.add_layer(
        composition_id,
        CompositionLayerInstance(
            uuid.uuid4(),
            ProjectResourceReference(mask_id),
            role="mask",
        ),
    )

    plan = document._canvas_resampling_owner.capture(
        composition_id,
        QSize(4, 6),
        mode=CanvasResamplingMode.SMOOTH,
    )
    assert document._canvas_resampling_owner.commit(
        document._canvas_resampling_owner.build(plan)
    )

    layer = document.resources.compositions.layers.layers_for_composition(
        composition_id
    )[0]
    assert isinstance(layer.source, ProjectResourceReference)
    replacement = document.masks.get_layer(layer.source.resource_id)
    assert replacement is not None
    assert replacement.coverage.raster.bounds is not None
    assert replacement.coverage.raster.bounds.width == 4
    assert replacement.coverage.raster.bounds.height == 6
    assert replacement.coverage.retained.items[0].geometry == retained.geometry
    assert replacement.coverage.retained.items[0].transform == LayerTransform(
        m11=2.0,
        m22=3.0,
    )
    original = document.masks.get_layer(mask_id)
    assert original is not None
    assert original.coverage.raster.bounds is not None
    assert original.coverage.raster.bounds.width == 2
    assert original.coverage.retained.items[0].transform == LayerTransform()


def test_crop_adds_exact_semantic_boundaries_with_atomic_history() -> None:
    """Retain source pixels while a durable clip prevents later reveal."""
    document = CanvasDocument()
    composition_id = document.create_composition_from_image(
        _image(QSize(4, 3), QColor("magenta"))
    )

    assert document.crop_layers_to_canvas(composition_id)

    layer = document.resources.compositions.layers.layers_for_composition(
        composition_id
    )[0]
    effect = layer.effects[-1]
    assert isinstance(effect, CanvasCropEffect)
    assert effect.points == (
        QRectF(0.0, 0.0, 4.0, 3.0).topLeft(),
        QRectF(0.0, 0.0, 4.0, 3.0).topRight(),
        QRectF(0.0, 0.0, 4.0, 3.0).bottomRight(),
        QRectF(0.0, 0.0, 4.0, 3.0).bottomLeft(),
    )
    assert document.resources.compositions.edit_controller.undo(composition_id)
    restored = document.resources.compositions.layers.layers_for_composition(
        composition_id
    )[0]
    assert restored.effects == ()
    assert document.resources.compositions.edit_controller.redo(composition_id)
    cropped = document.resources.compositions.layers.layers_for_composition(
        composition_id
    )[0]
    assert cropped.effects == (effect,)


def test_crop_remains_independent_when_a_user_vector_mask_is_replaced() -> None:
    """Keep the destructive crop boundary outside ordinary mask ownership."""
    document = CanvasDocument()
    composition_id = document.create_composition_from_image(
        _image(QSize(4, 3), QColor("yellow"))
    )
    target = document.resources.compositions.layers.layers_for_composition(
        composition_id
    )[0]
    assert document.crop_layers_to_canvas(composition_id)
    vector = document.vectors.assets.create(RasterBounds(0, 0, 4, 3))
    shape = CoverageGeometryFactory().rectangle(QRectF(0.0, 0.0, 2.0, 2.0))
    vector = vector.add(shape)
    assert document.vectors.assets.replace(vector)
    vector_layer = CompositionLayerInstance(
        uuid.uuid4(),
        ProjectResourceReference(vector.vector_id),
        role="vector",
    )
    assert document.resources.compositions.layers.add_layer(
        composition_id,
        vector_layer,
    )

    assert document.vectors.masks.attach(
        composition_id,
        composition_id,
        vector_layer.layer_id,
        target.layer_id,
        (shape.object_id,),
        inverted=False,
    )

    masked = document.resources.compositions.layers.layer(
        composition_id,
        target.layer_id,
    )
    assert masked is not None
    assert any(isinstance(item, CanvasCropEffect) for item in masked.effects)
    assert any(isinstance(item, VectorMaskEffect) for item in masked.effects)


def _image(size: QSize, color: QColor) -> QImage:
    """Return one premultiplied image fixture."""
    image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(color)
    return image
