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

"""Regression tests for single-owner translucent tile compositing."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRect
from PySide6.QtGui import QColor, QImage, QPainter, Qt, QTransform
from qpane.rendering.item_compositor import SceneItemCompositor
from qpane.scene.render_plan import RenderStrategy, SceneRenderPlan, TileRenderData
from qpane_test_support.render_compare import assert_images_match
from qpane_test_support.render_plan import make_render_plan


def _translucent_source(width: int, height: int) -> QImage:
    """Return a uniform translucent source that exposes repeated blending."""
    source = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    source.fill(QColor(68, 92, 220, 112))
    return source


def _tiles(
    source: QImage,
    *,
    tile_size: int,
    overlap: int,
    omitted: set[tuple[int, int]] | None = None,
) -> tuple[TileRenderData, ...]:
    """Return the ordinary overlapping tile products for one source."""
    omitted = omitted or set()
    stride = tile_size - overlap
    tiles: list[TileRenderData] = []
    for row, y_position in enumerate(range(0, source.height(), stride)):
        for column, x_position in enumerate(range(0, source.width(), stride)):
            if (row, column) in omitted:
                continue
            tiles.append(
                TileRenderData(
                    source.copy(x_position, y_position, tile_size, tile_size),
                    QPointF(x_position, y_position),
                )
            )
    return tuple(tiles)


def _draw(plan: SceneRenderPlan) -> QImage:
    """Composite one plan into a transparent target."""
    target = QImage(
        plan.qpane_rect.size(),
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    target.fill(Qt.GlobalColor.transparent)
    painter = QPainter(target)
    try:
        SceneItemCompositor().draw_visible_items(painter, plan)
    finally:
        painter.end()
    return target


def test_translucent_tiles_match_direct_render_without_overlap_seams() -> None:
    """Ready tiles and their fallback must apply source alpha exactly once."""
    source = _translucent_source(144, 96)
    bounds = QRect(0, 0, source.width(), source.height())
    direct = _draw(make_render_plan(bounds, source_image=source))
    tiled = _draw(
        make_render_plan(
            bounds,
            source_image=source,
            strategy=RenderStrategy.TILE,
            tiles_to_draw=_tiles(source, tile_size=64, overlap=8),
            tile_size=64,
            tile_overlap=8,
            max_tile_cols=3,
            max_tile_rows=2,
            visible_tile_range=(0, 1, 0, 2),
        )
    )

    assert_images_match(tiled, direct)


def test_translucent_fallback_matches_direct_when_tile_is_missing() -> None:
    """An unavailable tile must leave neither a gap nor a repeated-alpha region."""
    source = _translucent_source(144, 96)
    bounds = QRect(0, 0, source.width(), source.height())
    direct = _draw(make_render_plan(bounds, source_image=source))
    tiled = _draw(
        make_render_plan(
            bounds,
            source_image=source,
            strategy=RenderStrategy.TILE,
            tiles_to_draw=_tiles(
                source,
                tile_size=64,
                overlap=8,
                omitted={(0, 1)},
            ),
            tile_size=64,
            tile_overlap=8,
            max_tile_cols=3,
            max_tile_rows=2,
            visible_tile_range=(0, 1, 0, 2),
        )
    )

    assert_images_match(tiled, direct)


def test_translucent_tile_coverage_stays_exact_under_fractional_transform() -> None:
    """Fractional navigation transforms must not expose tile coverage boundaries."""
    source = _translucent_source(144, 96)
    viewport = QRect(0, 0, 240, 180)
    transform = QTransform()
    transform.translate(7.25, 8.5)
    transform.scale(1.37, 1.37)
    direct = _draw(
        make_render_plan(
            viewport,
            source_image=source,
            transform=transform,
            render_hint_enabled=True,
        )
    )
    tiled = _draw(
        make_render_plan(
            viewport,
            source_image=source,
            transform=transform,
            strategy=RenderStrategy.TILE,
            render_hint_enabled=True,
            tiles_to_draw=_tiles(source, tile_size=64, overlap=8),
            tile_size=64,
            tile_overlap=8,
            max_tile_cols=3,
            max_tile_rows=2,
            visible_tile_range=(0, 1, 0, 2),
        )
    )

    comparison_rect = QRect(16, 16, 180, 115)
    assert_images_match(
        tiled.copy(comparison_rect),
        direct.copy(comparison_rect),
    )
