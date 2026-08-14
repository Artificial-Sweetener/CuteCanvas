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
"""Exact domain semantics for selected raster pixel translation."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import cast

import numpy as np
from PySide6.QtGui import QColor, QImage

from cutecanvas.coverage import CoverageAsset, CoverageSnapshot, CoverageSurface
from cutecanvas.masks.mask import MaskLayer
from cutecanvas.masks.pixel_edits import MaskLayerPixelMutationOwner
from cutecanvas.masks.pixel_translation import MaskPixelTranslator
from cutecanvas.raster.color_surface import ColorRasterSurface
from cutecanvas.raster.pixel_translation import ColorPixelTranslator
from cutecanvas.resources import ProjectResourceReference
from cutecanvas.scene.pixel_fragments import RasterPixelFormat, RasterPixelFragment
from cutecanvas.types import RasterExtentPolicy
from qpane.scene.model import LayerDescriptor
from qpane.scene.raster import RasterBounds


def _coverage(values: list[int], *, x: int = 0) -> CoverageSnapshot:
    """Return one-row local selection coverage."""
    pixels = np.array([values], dtype=np.uint8)
    return CoverageSnapshot(
        RasterBounds(x, 0, len(values), 1),
        RasterExtentPolicy.EXPAND_ON_WRITE,
        pixels,
    )


def _mask(
    pixels: np.ndarray,
    *,
    extent_policy: RasterExtentPolicy = RasterExtentPolicy.FIXED,
) -> MaskLayer:
    """Return one hybrid mask fixture with raster-only initial authority."""
    mask_id = uuid.uuid4()
    return MaskLayer(
        mask_id,
        CoverageAsset(
            mask_id,
            CoverageSurface(pixels, extent_policy=extent_policy),
        ),
    )


def test_mask_translation_moves_values_without_overlap_smear() -> None:
    """Overlapping mask movement must read every value from pre-move pixels."""
    mask = _mask(np.array([[10, 20, 30]], dtype=np.uint8))
    translator = MaskPixelTranslator()

    transition = translator.move(mask, _coverage([255, 255]), 1, 0)

    assert transition is not None
    np.testing.assert_array_equal(
        mask.coverage.raster.snapshot_array(),
        np.array([[0, 10, 20]], dtype=np.uint8),
    )
    assert translator.restore(mask, transition, use_after=False)
    np.testing.assert_array_equal(
        mask.coverage.raster.snapshot_array(),
        np.array([[10, 20, 30]], dtype=np.uint8),
    )
    assert translator.restore(mask, transition, use_after=True)
    np.testing.assert_array_equal(
        mask.coverage.raster.snapshot_array(),
        np.array([[0, 10, 20]], dtype=np.uint8),
    )


def test_mask_translation_treats_zero_as_noncontributing_content() -> None:
    """Moving transparent mask storage must preserve destination coverage."""
    mask = _mask(np.array([[0, 255]], dtype=np.uint8))

    transition = MaskPixelTranslator().move(mask, _coverage([255]), 1, 0)

    assert transition is None
    np.testing.assert_array_equal(
        mask.coverage.raster.snapshot_array(),
        np.array([[0, 255]], dtype=np.uint8),
    )


def test_mask_translation_preserves_destination_beneath_internal_holes() -> None:
    """Transparent holes inside selected bounds must not clear moved-over content."""
    mask = _mask(np.array([[255, 0, 100, 200]], dtype=np.uint8))

    transition = MaskPixelTranslator().move(
        mask,
        _coverage([255, 255]),
        2,
        0,
    )

    assert transition is not None
    np.testing.assert_array_equal(
        mask.coverage.raster.snapshot_array(),
        np.array([[0, 0, 255, 200]], dtype=np.uint8),
    )


def test_mask_fragment_placement_rejects_transparent_write_coverage() -> None:
    """A malformed fragment cannot use transparent scalar storage as replacement."""
    mask = _mask(np.array([[100, 200]], dtype=np.uint8))
    bounds = RasterBounds(0, 0, 2, 1)
    fragment = RasterPixelFragment(
        bounds,
        RasterPixelFormat.COVERAGE8,
        np.array([[255, 0]], dtype=np.uint8),
        CoverageSnapshot(
            bounds,
            RasterExtentPolicy.FIXED,
            np.array([[255, 255]], dtype=np.uint8),
        ),
    )

    transition = MaskPixelTranslator().place(mask, fragment, bounds)

    assert transition is not None
    np.testing.assert_array_equal(
        mask.coverage.raster.snapshot_array(),
        np.array([[255, 200]], dtype=np.uint8),
    )


def test_mask_translation_preserves_soft_selection_coverage() -> None:
    """Feathered selection must proportionally clear and place mask values."""
    mask = _mask(np.array([[200, 100]], dtype=np.uint8))

    transition = MaskPixelTranslator().move(mask, _coverage([128]), 1, 0)

    assert transition is not None
    np.testing.assert_array_equal(
        mask.coverage.raster.snapshot_array(),
        np.array([[100, 150]], dtype=np.uint8),
    )


def test_expanding_mask_translation_retains_off_surface_values() -> None:
    """Expand-on-write movement must retain translated local pixels and undo bounds."""
    mask = _mask(
        np.array([[255, 0]], dtype=np.uint8),
        extent_policy=RasterExtentPolicy.EXPAND_ON_WRITE,
    )
    translator = MaskPixelTranslator()

    transition = translator.move(mask, _coverage([255]), -2, 0)

    assert transition is not None
    assert mask.coverage.raster.bounds == RasterBounds(-2, 0, 4, 1)
    np.testing.assert_array_equal(
        mask.coverage.raster.snapshot_array(),
        np.array([[255, 0, 0, 0]], dtype=np.uint8),
    )
    assert translator.restore(mask, transition, use_after=False)
    assert mask.coverage.raster.bounds == RasterBounds(0, 0, 2, 1)
    np.testing.assert_array_equal(
        mask.coverage.raster.snapshot_array(),
        np.array([[255, 0]], dtype=np.uint8),
    )


def test_fixed_mask_translation_clips_destination_without_growing_bounds() -> None:
    """Fixed movement may discard off-surface payload while clearing its origin."""
    mask = _mask(
        np.array([[0, 255]], dtype=np.uint8),
        extent_policy=RasterExtentPolicy.FIXED,
    )

    transition = MaskPixelTranslator().move(mask, _coverage([255], x=1), 2, 0)

    assert transition is not None
    assert mask.coverage.raster.bounds == RasterBounds(0, 0, 2, 1)
    np.testing.assert_array_equal(
        mask.coverage.raster.snapshot_array(),
        np.array([[0, 0]], dtype=np.uint8),
    )


def test_mask_owner_exposes_nonzero_content_as_binary_movement_occupancy() -> None:
    """Zero mask pixels should not travel while every painted soft value remains data."""
    mask = _mask(np.array([[0, 1, 128, 255]], dtype=np.uint8))

    class Lookup:
        """Resolve the single mask used by the source-domain owner."""

        def get_layer(self, mask_id: uuid.UUID) -> MaskLayer | None:
            """Return the fixture mask for its identifier."""
            return mask if mask_id == mask.mask_id else None

    owner = MaskLayerPixelMutationOwner(Lookup(), lambda _mask_id, _bounds: None)
    descriptor = cast(
        LayerDescriptor,
        SimpleNamespace(source=ProjectResourceReference(mask.mask_id)),
    )

    coverage = owner.content_coverage(descriptor, RasterBounds(0, 0, 4, 1))

    assert coverage is not None
    np.testing.assert_array_equal(
        coverage.pixels,
        np.array([[0, 255, 255, 255]], dtype=np.uint8),
    )


def test_color_translation_moves_premultiplied_pixels_without_smear() -> None:
    """RGBA movement must clear origin and source-over immutable selected pixels."""
    image = QImage(3, 1, QImage.Format_ARGB32_Premultiplied)
    image.setPixelColor(0, 0, QColor(255, 0, 0, 255))
    image.setPixelColor(1, 0, QColor(0, 255, 0, 255))
    image.setPixelColor(2, 0, QColor(0, 0, 255, 255))
    surface = ColorRasterSurface(image)
    translator = ColorPixelTranslator()

    transition = translator.move(surface, _coverage([255, 255]), 1, 0)

    assert transition is not None
    result = surface.snapshot_qimage()
    assert result.pixelColor(0, 0).alpha() == 0
    assert result.pixelColor(1, 0) == QColor(255, 0, 0, 255)
    assert result.pixelColor(2, 0) == QColor(0, 255, 0, 255)
    assert translator.restore(surface, transition, use_after=False)
    restored = surface.snapshot_qimage()
    assert restored.pixelColor(0, 0) == QColor(255, 0, 0, 255)
    assert restored.pixelColor(1, 0) == QColor(0, 255, 0, 255)
    assert restored.pixelColor(2, 0) == QColor(0, 0, 255, 255)
