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

"""Contract proof for exact settled raster request geometry."""

from __future__ import annotations

import math
import uuid

from ferrastra import RasterReconstructionSpace
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QTransform
from qpane.rendering.exact_raster_geometry import (
    exact_axis_sampling_grid,
    exact_visible_tile_requests,
)
from qpane.rendering.render_sampling_grid import AffineSamplingGrid
from qpane.rendering.render_tile_cache import RenderTileCache
from qpane.rendering.render_tile_geometry import RenderTileKey, RenderTileRequest
from qpane.rendering.render_tile_types import RenderTileProduct
from qpane.scene.raster import RasterBounds
from qpane.scene.raster_sampling import RasterExactSampling


def test_exact_grid_preserves_physical_scale_and_fractional_phase() -> None:
    """The grid maps every sample center onto a physical pixel center."""
    transform = QTransform()
    transform.translate(10.25, -3.125)
    transform.scale(1.5, 0.75)
    grid = exact_axis_sampling_grid(transform, 2.0, RasterBounds(0, 0, 800, 600))

    assert grid is not None
    assert grid.scale_x == 3.0
    assert grid.scale_y == 1.5
    for axis_phase, axis_step, axis_scale, translation in (
        (grid.phase_x, grid.step_x, transform.m11(), transform.dx()),
        (grid.phase_y, grid.step_y, transform.m22(), transform.dy()),
    ):
        physical_boundary = (axis_phase * axis_scale + translation) * 2.0
        assert math.isclose(physical_boundary, round(physical_boundary), abs_tol=1e-9)
        assert math.isclose(axis_step * abs(axis_scale) * 2.0, 1.0)


def test_integer_physical_pan_reuses_the_same_exact_grid() -> None:
    """Whole-device-pixel navigation retains exact cached tile identities."""
    first = QTransform.fromScale(1.25, 1.25)
    first.translate(0.2, -0.4)
    second = QTransform(first)
    second.setMatrix(
        first.m11(),
        first.m12(),
        first.m13(),
        first.m21(),
        first.m22(),
        first.m23(),
        first.dx() + 0.5,
        first.dy() - 1.0,
        first.m33(),
    )
    bounds = RasterBounds(0, 0, 4096, 4096)

    assert exact_axis_sampling_grid(first, 2.0, bounds) == exact_axis_sampling_grid(
        second,
        2.0,
        bounds,
    )


def test_exact_requests_keep_density_instead_of_substituting_a_lower_scale() -> None:
    """Insufficient exact-product memory declines refinement explicitly."""
    transform = QTransform.fromScale(2.3, 1.7)
    common = {
        "source_kind": "raster-exact",
        "source_id": uuid.UUID(int=1),
        "revision_key": 4,
        "fallback_key": 3,
        "bounds": RasterBounds(0, 0, 4000, 3000),
        "source_to_panel": transform,
        "panel_rect": QRectF(0.0, 0.0, 1200.0, 900.0),
        "device_pixel_ratio": 1.0,
        "exact_sampling": RasterExactSampling.NEAREST,
    }

    assert exact_visible_tile_requests(budget_bytes=1, **common) is None
    requests = exact_visible_tile_requests(budget_bytes=32 * 1024 * 1024, **common)

    assert requests is not None
    assert requests
    grids = tuple(request.key.sampling_grid for request in requests)
    assert all(grid is not None for grid in grids)
    assert all(grid is not None and grid.scale_x == 2.3 for grid in grids)
    assert all(grid is not None and grid.scale_y == 1.7 for grid in grids)
    assert all(
        math.isclose(request.paint_rect.width() * 2.3, 516.0)
        and math.isclose(request.paint_rect.height() * 1.7, 516.0)
        for request in requests
    )


def test_rotated_mapping_declines_axis_aligned_sampling() -> None:
    """Rotation remains distinguishable from the exact sampled-view contract."""
    transform = QTransform()
    transform.rotate(15.0)

    assert (
        exact_axis_sampling_grid(
            transform,
            1.0,
            RasterBounds(0, 0, 100, 100),
        )
        is None
    )


def test_rotated_mapping_produces_bounded_panel_physical_tiles() -> None:
    """General affine demand retains the exact device grid and inverse mapping."""
    transform = QTransform()
    transform.translate(80.0, 40.0)
    transform.rotate(15.0)
    requests = exact_visible_tile_requests(
        source_kind="raster-exact",
        source_id=uuid.UUID(int=2),
        revision_key=5,
        fallback_key=4,
        bounds=RasterBounds(0, 0, 100, 80),
        source_to_panel=transform,
        panel_rect=QRectF(0.0, 0.0, 300.0, 200.0),
        device_pixel_ratio=2.0,
        budget_bytes=16 * 1024 * 1024,
        exact_sampling=RasterExactSampling.AFFINE_BILINEAR,
    )

    assert requests is not None and requests
    assert all(
        isinstance(request.key.sampling_grid, AffineSamplingGrid)
        for request in requests
    )
    assert all(
        math.isclose(request.paint_rect.width() * 2.0, 516.0) for request in requests
    )


def test_cache_never_uses_an_opposite_sampling_contract_as_fallback() -> None:
    """Nearest and reconstructed products remain incompatible cache identities."""
    source_id = uuid.UUID(int=9)
    common = {
        "source_kind": "raster-exact",
        "source_id": source_id,
        "fallback_key": "geometry",
        "revision_key": "revision",
        "scale": 2.0,
        "column": 0,
        "row": 0,
    }
    nearest = RenderTileKey(**common, exact_sampling=RasterExactSampling.NEAREST)
    lanczos = RenderTileKey(**common, exact_sampling=RasterExactSampling.LANCZOS3)
    image = QImage(4, 4, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("red"))
    rect = QRectF(0.0, 0.0, 4.0, 4.0)
    cache = RenderTileCache()
    cache.admit((RenderTileProduct(nearest, rect, image, rect),))

    assert cache.products((lanczos,)) is None
    assert (
        cache.presentation_products((RenderTileRequest(lanczos, rect, rect),)) is None
    )


def test_cache_identity_separates_reconstruction_working_spaces() -> None:
    """Encoded and linear reconstruction products must never alias."""
    common = {
        "source_kind": "raster-exact",
        "source_id": uuid.UUID(int=11),
        "fallback_key": "geometry",
        "revision_key": "revision",
        "scale": 1.0,
        "column": 0,
        "row": 0,
        "exact_sampling": RasterExactSampling.LANCZOS3,
    }
    encoded = RenderTileKey(
        **common,
        reconstruction_space=RasterReconstructionSpace.SRGB_ENCODED,
    )
    linear = RenderTileKey(
        **common,
        reconstruction_space=RasterReconstructionSpace.SRGB_LINEAR,
    )
    image = QImage(4, 4, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("red"))
    rect = QRectF(0.0, 0.0, 4.0, 4.0)
    cache = RenderTileCache()
    cache.admit((RenderTileProduct(encoded, rect, image, rect),))

    assert encoded != linear
    assert cache.products((linear,)) is None


def test_cache_never_reprojects_an_exact_product_from_an_old_pixel_phase() -> None:
    """A pan-phase change returns to preview instead of shifting retained exact pixels."""
    source_id = uuid.UUID(int=10)
    first_grid = exact_axis_sampling_grid(
        QTransform.fromScale(2.0, 2.0),
        1.0,
        RasterBounds(0, 0, 4, 4),
    )
    moved = QTransform.fromScale(2.0, 2.0)
    moved.translate(0.125, 0.0)
    moved_grid = exact_axis_sampling_grid(
        moved,
        1.0,
        RasterBounds(0, 0, 4, 4),
    )
    assert (
        first_grid is not None and moved_grid is not None and first_grid != moved_grid
    )
    common = {
        "source_kind": "raster-exact",
        "source_id": source_id,
        "fallback_key": "geometry",
        "revision_key": "revision",
        "scale": 2.0,
        "column": 0,
        "row": 0,
        "exact_sampling": RasterExactSampling.NEAREST,
    }
    first = RenderTileKey(**common, sampling_grid=first_grid)
    changed_phase = RenderTileKey(**common, sampling_grid=moved_grid)
    image = QImage(4, 4, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("red"))
    rect = QRectF(0.0, 0.0, 4.0, 4.0)
    cache = RenderTileCache()
    cache.admit((RenderTileProduct(first, rect, image, rect),))

    request = RenderTileRequest(changed_phase, rect, rect)
    assert cache.presentation_products((request,)) is None
