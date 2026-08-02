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
"""Tests for the authoritative hybrid coverage document."""

from __future__ import annotations

import uuid

import numpy as np
from cutecanvas.coverage import (
    CoverageAsset,
    CoverageCombineMode,
    CoverageDocument,
    CoverageDocumentEvaluator,
    CoverageItemMoveSession,
    CoverageSnapshot,
    CoverageSurface,
    RasterCoverageItem,
    VectorCoverageItem,
)
from cutecanvas.snapping import bounds_candidates
from cutecanvas.types import RasterExtentPolicy
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor
from qpane.scene.affine import LayerTransform
from qpane.scene.raster import RasterBounds
from qpane.vector.model import VectorObject
from qpane.vector.public import VectorObjectKind, VectorShapeKind, VectorStyle

from tests.harness.timing import average_interaction_latency_ms, interaction_clock


def _rectangle(x: float, y: float, width: float, height: float) -> VectorObject:
    """Return one solid semantic rectangle."""
    return VectorObject(
        object_id=uuid.uuid4(),
        kind=VectorObjectKind.SHAPE,
        local_bounds=(x, y, width, height),
        transform=LayerTransform(),
        style=VectorStyle(fill=QColor("white"), stroke=None),
        shape_kind=VectorShapeKind.RECTANGLE,
    )


def test_retained_vector_geometry_evaluates_without_flattening() -> None:
    item = VectorCoverageItem(uuid.uuid4(), _rectangle(10.0, 20.0, 30.0, 40.0))
    document = CoverageDocument().add(item)
    evaluator = CoverageDocumentEvaluator(tile_size=16)

    assert document.item(item.item_id) is item
    assert evaluator.content_bounds(document) == RasterBounds(10, 20, 30, 40)
    snapshot = evaluator.rasterize(document)
    assert snapshot.bounds == RasterBounds(10, 20, 30, 40)
    assert snapshot.pixels.min() == 255


def test_vector_manipulation_bounds_preserve_fractional_authored_geometry() -> None:
    """Retained vectors must not quantize manipulation geometry to raster cells."""
    rectangle = QRectF(
        287.536231884058,
        171.88405797101453,
        591.304347826087,
        507.82608695652175,
    )
    item = VectorCoverageItem(
        uuid.uuid4(),
        _rectangle(
            rectangle.x(),
            rectangle.y(),
            rectangle.width(),
            rectangle.height(),
        ),
    )
    document = CoverageDocument().add(item)
    evaluator = CoverageDocumentEvaluator()
    asset = CoverageAsset(
        document.document_id,
        CoverageSurface(
            None,
            extent_policy=RasterExtentPolicy.EXPAND_ON_WRITE,
        ),
        retained=document,
        evaluator=evaluator,
    )

    assert evaluator.vector_content_bounds(document) == rectangle
    assert asset.manipulation_bounds() == rectangle
    assert evaluator.content_bounds(document) == RasterBounds(287, 171, 592, 509)


def test_vector_manipulation_bounds_apply_boolean_geometry_continuously() -> None:
    """Coverage algebra should produce one exact continuous vector envelope."""
    first = VectorCoverageItem(
        uuid.uuid4(),
        _rectangle(10.25, 20.5, 100.5, 80.25),
    )
    intersection = VectorCoverageItem(
        uuid.uuid4(),
        _rectangle(40.75, 30.125, 90.0, 40.5),
        CoverageCombineMode.INTERSECT,
    )
    document = CoverageDocument().add(first).add(intersection)

    assert CoverageDocumentEvaluator().vector_content_bounds(document) == QRectF(
        40.75,
        30.125,
        70.0,
        40.5,
    )


def test_ordered_coverage_algebra_preserves_transparent_holes() -> None:
    document = (
        CoverageDocument()
        .add(VectorCoverageItem(uuid.uuid4(), _rectangle(0.0, 0.0, 20.0, 20.0)))
        .add(
            VectorCoverageItem(
                uuid.uuid4(),
                _rectangle(5.0, 5.0, 10.0, 10.0),
                CoverageCombineMode.SUBTRACT,
            )
        )
    )
    snapshot = CoverageDocumentEvaluator(tile_size=8).rasterize(document)

    assert snapshot.bounds == RasterBounds(0, 0, 20, 20)
    assert snapshot.pixels[2, 2] == 255
    assert snapshot.pixels[10, 10] == 0


def test_content_bounds_ignore_transparent_raster_storage() -> None:
    pixels = np.zeros((64, 64), dtype=np.uint8)
    pixels[22:27, 31:39] = 255
    item = RasterCoverageItem(
        uuid.uuid4(),
        CoverageSnapshot(
            RasterBounds(-100, -200, 64, 64),
            RasterExtentPolicy.EXPAND_ON_WRITE,
            pixels,
        ),
    )
    document = CoverageDocument().add(item)

    assert CoverageDocumentEvaluator().content_bounds(document) == RasterBounds(
        -69, -178, 8, 5
    )


def test_replacing_geometry_is_one_immutable_document_revision() -> None:
    first = VectorCoverageItem(uuid.uuid4(), _rectangle(0.0, 0.0, 4.0, 4.0))
    second = VectorCoverageItem(uuid.uuid4(), _rectangle(50.0, 60.0, 7.0, 8.0))
    document = CoverageDocument().add(first).replaced_by(second)

    assert document.revision == 2
    assert document.items == (second,)
    assert CoverageDocumentEvaluator().content_bounds(document) == RasterBounds(
        50, 60, 7, 8
    )


def test_hybrid_asset_keeps_raster_paint_and_retained_geometry_editable() -> None:
    raster_pixels = np.zeros((16, 16), dtype=np.uint8)
    raster_pixels[2:5, 3:7] = 255
    asset_id = uuid.uuid4()
    asset = CoverageAsset(
        asset_id,
        CoverageSurface(
            raster_pixels,
            bounds=RasterBounds(0, 0, 16, 16),
            extent_policy=RasterExtentPolicy.EXPAND_ON_WRITE,
        ),
    )
    retained = VectorCoverageItem(
        uuid.uuid4(),
        _rectangle(30.0, 40.0, 8.0, 9.0),
    )

    assert asset.append(retained)
    assert asset.content_bounds() == RasterBounds(3, 2, 35, 47)
    assert asset.has_retained_items
    assert asset.rasterize()
    assert not asset.has_retained_items
    assert asset.raster.content_bounds() == RasterBounds(3, 2, 35, 47)


def test_vector_replace_discards_raster_bounds_without_quantizing_geometry() -> None:
    """A retained replacement should supersede raster geometry continuously."""
    raster_pixels = np.full((8, 8), 255, dtype=np.uint8)
    rectangle = QRectF(30.25, 40.5, 8.75, 9.125)
    evaluator = CoverageDocumentEvaluator()
    asset = CoverageAsset(
        uuid.uuid4(),
        CoverageSurface(
            raster_pixels,
            bounds=RasterBounds(-100, -200, 8, 8),
            extent_policy=RasterExtentPolicy.EXPAND_ON_WRITE,
        ),
        evaluator=evaluator,
    )
    assert asset.append(
        VectorCoverageItem(
            uuid.uuid4(),
            _rectangle(-500.5, -400.25, 20.0, 30.0),
        )
    )
    assert asset.append(
        VectorCoverageItem(
            uuid.uuid4(),
            _rectangle(
                rectangle.x(),
                rectangle.y(),
                rectangle.width(),
                rectangle.height(),
            ),
            CoverageCombineMode.REPLACE,
        )
    )

    assert evaluator.vector_content_bounds(asset.retained) == QRectF(
        30.25,
        40.5,
        8.75,
        9.125,
    )
    assert asset.manipulation_bounds() == rectangle


def test_added_vector_unions_exact_geometry_with_discrete_raster_cells() -> None:
    """Hybrid additive authorship should retain its exact outer vector edge."""
    raster_pixels = np.full((8, 8), 255, dtype=np.uint8)
    rectangle = QRectF(30.25, 40.5, 8.75, 9.125)
    asset = CoverageAsset(
        uuid.uuid4(),
        CoverageSurface(
            raster_pixels,
            bounds=RasterBounds(0, 0, 8, 8),
            extent_policy=RasterExtentPolicy.EXPAND_ON_WRITE,
        ),
    )
    assert asset.append(
        VectorCoverageItem(
            uuid.uuid4(),
            _rectangle(
                rectangle.x(),
                rectangle.y(),
                rectangle.width(),
                rectangle.height(),
            ),
        )
    )

    assert asset.manipulation_bounds() == QRectF(0.0, 0.0, 39.0, 49.625)


def test_retained_item_movement_uses_shared_snapping_without_rasterizing() -> None:
    """Coverage-item movement should retain geometry and shared snap behavior."""
    item = VectorCoverageItem(uuid.uuid4(), _rectangle(0.0, 0.0, 20.0, 20.0))
    document = CoverageDocument().add(item)
    session = CoverageItemMoveSession(
        document,
        item.item_id,
        bounds_candidates("other", QRectF(100.0, 200.0, 20.0, 20.0)),
    )

    preview, result = session.resolve(
        QPointF(79.0, 179.0), scene_units_per_device_pixel=1.0
    )

    moved = preview.item(item.item_id)
    assert isinstance(moved, VectorCoverageItem)
    assert moved.geometry is item.geometry
    assert moved.transform.dx == 80.0
    assert moved.transform.dy == 180.0
    assert result.snapped_x and result.snapped_y


def test_thousand_sparse_vectors_keep_tiled_content_bounds_bounded() -> None:
    """Sparse retained geometry should cull non-intersecting items per tile."""
    document = CoverageDocument(
        items=tuple(
            VectorCoverageItem(
                uuid.uuid4(),
                _rectangle(float(index * 32), 0.0, 8.0, 8.0),
            )
            for index in range(1000)
        )
    )
    evaluator = CoverageDocumentEvaluator(tile_size=512)

    manipulation_bounds = evaluator.vector_content_bounds(document)
    manipulation_elapsed_ms = average_interaction_latency_ms(
        lambda: CoverageDocumentEvaluator(tile_size=512).vector_content_bounds(
            document
        ),
        repetitions=32,
    )

    started = interaction_clock()
    bounds = evaluator.content_bounds(document)
    elapsed = interaction_clock() - started

    assert manipulation_bounds == QRectF(0.0, 0.0, 31976.0, 8.0)
    assert manipulation_elapsed_ms < 32.0
    assert bounds == RasterBounds(0, 0, 31976, 8)
    assert elapsed < 4.0
