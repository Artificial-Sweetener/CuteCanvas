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
"""Exactness and retention tests for persistent vector-mask geometry."""

from __future__ import annotations

import uuid
from dataclasses import replace

from cutecanvas.vector.mask_cache import VectorMaskPathCache
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QPainterPath
from qpane.scene.affine import LayerTransform
from qpane.scene.raster import RasterBounds
from qpane.vector.model import VectorDocument, VectorObject
from qpane.vector.public import (
    VectorFillRule,
    VectorObjectKind,
    VectorPathCommand,
    VectorPathCommandKind,
    VectorShapeKind,
    VectorStyle,
)


def test_vector_mask_path_cache_preserves_union_holes_and_object_subsets() -> None:
    """Balanced unions must preserve overlap, fill rules, and subset identity."""
    overlapping = _rectangle(0.0, 0.0, 20.0, 20.0)
    second = _rectangle(10.0, 0.0, 20.0, 20.0)
    donut = _donut(40.0, 0.0)
    document = VectorDocument(
        uuid.uuid4(),
        RasterBounds(0, 0, 80, 40),
        (overlapping, second, donut),
        1,
    )
    cache = VectorMaskPathCache()

    combined = cache.path(document, None)
    assert combined.contains(QPointF(15.0, 10.0))
    assert combined.contains(QPointF(42.0, 2.0))
    assert not combined.contains(QPointF(50.0, 10.0))

    subset = cache.path(document, frozenset((second.object_id,)))
    assert not subset.contains(QPointF(5.0, 10.0))
    assert subset.contains(QPointF(15.0, 10.0))
    assert not subset.contains(QPointF(42.0, 2.0))


def test_vector_mask_path_cache_rebuilds_only_changed_tree_result_exactly() -> None:
    """Persistent updates must equal a cold rebuild and obey cache eviction."""
    objects = tuple(
        _rectangle(float(index * 4), float(index % 3), 8.0, 8.0) for index in range(32)
    )
    document = VectorDocument(
        uuid.uuid4(),
        RasterBounds(0, 0, 160, 20),
        objects,
        1,
    )
    cache = VectorMaskPathCache()
    cache.path(document, None)
    moved = replace(objects[17], transform=LayerTransform(dx=7.5, dy=-2.0))
    updated = document.replace_object(moved)

    incremental = cache.path(updated, None)
    cold = VectorMaskPathCache().path(updated, None)
    for x in range(-2, 150, 3):
        for y in range(-4, 16, 2):
            point = QPointF(float(x), float(y))
            assert incremental.contains(point) == cold.contains(point)

    assert cache.entry_count == 1
    assert cache.usage_bytes > 0
    cache.set_budget(0)
    assert cache.entry_count == 0
    assert cache.usage_bytes == 0


def test_vector_mask_hot_branch_and_alternating_edits_remain_exact() -> None:
    """Hot-leaf reuse and a subsequent different edit must match cold unions."""
    objects = tuple(
        _rectangle(float((index * 11) % 70), float((index * 7) % 30), 14.0, 12.0)
        for index in range(24)
    )
    document = VectorDocument(
        uuid.uuid4(),
        RasterBounds(0, 0, 100, 60),
        objects,
        1,
    )
    cache = VectorMaskPathCache()
    cache.path(document, None)

    for offset in (2.0, 4.0, 6.0):
        document = document.replace_object(
            replace(objects[-1], transform=LayerTransform(dx=offset, dy=-offset))
        )
        _assert_paths_equal(cache.path(document, None), _cold_path(document))

    document = document.replace_object(
        replace(objects[3], transform=LayerTransform(dx=-9.0, dy=5.0))
    )
    _assert_paths_equal(cache.path(document, None), _cold_path(document))


def _cold_path(document: VectorDocument) -> QPainterPath:
    """Return an independently rebuilt exact mask path."""
    return VectorMaskPathCache().path(document, None)


def _assert_paths_equal(actual: QPainterPath, expected: QPainterPath) -> None:
    """Compare filled geometry over a dense deterministic sample grid."""
    for x in range(-4, 108, 2):
        for y in range(-8, 70, 2):
            point = QPointF(float(x), float(y))
            assert actual.contains(point) == expected.contains(point)


def _rectangle(x: float, y: float, width: float, height: float) -> VectorObject:
    """Return one filled semantic rectangle."""
    return VectorObject(
        uuid.uuid4(),
        VectorObjectKind.SHAPE,
        (x, y, width, height),
        LayerTransform(),
        VectorStyle(fill=QColor("white"), stroke=None),
        shape_kind=VectorShapeKind.RECTANGLE,
    )


def _donut(x: float, y: float) -> VectorObject:
    """Return one even-odd path with an intentional center hole."""
    commands = (
        VectorPathCommand(VectorPathCommandKind.MOVE, (QPointF(x, y),)),
        VectorPathCommand(VectorPathCommandKind.LINE, (QPointF(x + 20.0, y),)),
        VectorPathCommand(
            VectorPathCommandKind.LINE,
            (QPointF(x + 20.0, y + 20.0),),
        ),
        VectorPathCommand(VectorPathCommandKind.LINE, (QPointF(x, y + 20.0),)),
        VectorPathCommand(VectorPathCommandKind.CLOSE),
        VectorPathCommand(
            VectorPathCommandKind.MOVE,
            (QPointF(x + 6.0, y + 6.0),),
        ),
        VectorPathCommand(
            VectorPathCommandKind.LINE,
            (QPointF(x + 14.0, y + 6.0),),
        ),
        VectorPathCommand(
            VectorPathCommandKind.LINE,
            (QPointF(x + 14.0, y + 14.0),),
        ),
        VectorPathCommand(
            VectorPathCommandKind.LINE,
            (QPointF(x + 6.0, y + 14.0),),
        ),
        VectorPathCommand(VectorPathCommandKind.CLOSE),
    )
    return VectorObject(
        uuid.uuid4(),
        VectorObjectKind.PATH,
        (x, y, 20.0, 20.0),
        LayerTransform(),
        VectorStyle(
            fill=QColor("white"),
            stroke=None,
            fill_rule=VectorFillRule.EVEN_ODD,
        ),
        path=commands,
    )
