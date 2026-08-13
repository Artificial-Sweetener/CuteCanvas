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
"""Structure-aware selected-pixel translation for premultiplied RGBA."""

from __future__ import annotations

import numpy as np
from cutecanvas.coverage import CoverageSnapshot
from cutecanvas.scene.pixel_fragments import RasterPixelFormat, RasterPixelFragment
from cutecanvas.scene.pixel_transitions import (
    RasterPixelTransition,
    raster_edit_patch_bounds,
)
from cutecanvas.types import RasterExtentPolicy
from qpane.sdk.scene import RasterBounds

from .color_surface import ColorRasterSurface


class ColorPixelTranslator:
    """Move premultiplied pixels using selection-aware source-over semantics."""

    def move(
        self,
        surface: ColorRasterSurface,
        coverage: CoverageSnapshot,
        delta_x: int,
        delta_y: int,
    ) -> RasterPixelTransition | None:
        """Apply selected pixels from an immutable pre-move patch."""
        bounds = coverage.bounds
        if bounds is None or not surface.bounds.contains(bounds):
            return None
        transition = self.preview_fragment_move(
            surface,
            RasterPixelFragment(
                bounds,
                RasterPixelFormat.PREMULTIPLIED_ARGB32,
                surface.capture_region(bounds),
                coverage,
            ),
            delta_x,
            delta_y,
            cut_source=True,
        )
        if transition is None:
            return None
        return transition if self.restore(surface, transition, use_after=True) else None

    def preview_fragment_move(
        self,
        surface: ColorRasterSurface,
        fragment: RasterPixelFragment,
        delta_x: int,
        delta_y: int,
        *,
        cut_source: bool,
    ) -> RasterPixelTransition | None:
        """Compose an exact premultiplied fragment transition without mutation."""
        if fragment.pixel_format is not RasterPixelFormat.PREMULTIPLIED_ARGB32:
            return None
        source_bounds = fragment.bounds
        surface_bounds = surface.bounds
        source_bounds = source_bounds.intersection(surface_bounds)
        if source_bounds is None:
            return None
        selection = _coverage_region(
            fragment.contribution_coverage,
            source_bounds,
        )
        if not np.any(selection):
            return None
        destination_bounds = source_bounds.translated(delta_x, delta_y)
        after_bounds = (
            surface_bounds
            if surface.extent_policy is RasterExtentPolicy.FIXED
            else surface_bounds.united(destination_bounds)
        )
        patch_bounds = raster_edit_patch_bounds(
            source_bounds,
            destination_bounds,
            after_bounds,
        )
        if patch_bounds is None:
            return None
        before = surface.capture_region(patch_bounds)
        after = np.array(before, copy=True)
        fragment_array_bounds = RasterBounds(
            0,
            0,
            fragment.bounds.width,
            fragment.bounds.height,
        )
        fragment_source_region = RasterBounds(
            source_bounds.x - fragment.bounds.x,
            source_bounds.y - fragment.bounds.y,
            source_bounds.width,
            source_bounds.height,
        )
        source_pixels = _region(
            fragment.pixels,
            fragment_array_bounds,
            fragment_source_region,
        )
        minimum_selection = int(selection.min())
        hard_full_selection = minimum_selection == 255
        hard_selection = hard_full_selection or (
            minimum_selection == 0
            and int(selection.max()) == 255
            and not np.any((selection != 0) & (selection != 255))
        )
        source_after = _region(after, patch_bounds, source_bounds)
        if hard_full_selection:
            source_after.fill(0)
        elif hard_selection:
            source_after[selection != 0] = 0
        else:
            source_selection = selection.astype(np.uint16)[:, :, np.newaxis]
            remaining = (
                source_pixels.astype(np.uint16) * (255 - source_selection) + 127
            ) // 255
            np.copyto(source_after, remaining.astype(np.uint8))
        if not cut_source:
            np.copyto(source_after, source_pixels)
        destination = destination_bounds.intersection(patch_bounds)
        if destination is not None:
            source_for_destination = destination.translated(-delta_x, -delta_y)
            source_offset = RasterBounds(
                source_for_destination.x - source_bounds.x,
                source_for_destination.y - source_bounds.y,
                source_for_destination.width,
                source_for_destination.height,
            )
            source_array_bounds = RasterBounds(
                0,
                0,
                source_bounds.width,
                source_bounds.height,
            )
            moved = _region(source_pixels, source_array_bounds, source_offset)
            destination_pixels = _region(after, patch_bounds, destination)
            destination_selection = _region(
                selection,
                source_array_bounds,
                source_offset,
            )
            if hard_full_selection and int(moved[:, :, 3].min()) == 255:
                np.copyto(destination_pixels, moved)
            elif hard_selection:
                selected = destination_selection != 0
                selected_source = moved[selected]
                if selected_source.size and np.all(selected_source[:, 3] == 255):
                    destination_pixels[selected] = selected_source
                elif selected_source.size:
                    selected_wide = selected_source.astype(np.uint16)
                    destination_wide = destination_pixels[selected].astype(np.uint16)
                    inverse_alpha = 255 - selected_wide[:, 3:4]
                    replacement = (
                        selected_wide + (destination_wide * inverse_alpha + 127) // 255
                    )
                    destination_pixels[selected] = np.minimum(
                        replacement,
                        255,
                    ).astype(np.uint8)
            else:
                selected = destination_selection.astype(np.uint16)[:, :, np.newaxis]
                selected_pixels = (moved.astype(np.uint16) * selected + 127) // 255
                inverse_alpha = 255 - selected_pixels[:, :, 3:4]
                replacement = (
                    selected_pixels
                    + (destination_pixels.astype(np.uint16) * inverse_alpha + 127)
                    // 255
                )
                np.copyto(
                    destination_pixels,
                    np.minimum(replacement, 255).astype(np.uint8),
                )
        if np.array_equal(before, after) and after_bounds == surface_bounds:
            return None
        transition = RasterPixelTransition._adopt_detached(
            patch_bounds,
            surface_bounds,
            after_bounds,
            before,
            after,
        )
        return transition

    def restore(
        self,
        surface: ColorRasterSurface,
        transition: RasterPixelTransition,
        *,
        use_after: bool,
    ) -> bool:
        """Restore one side of an exact color-raster movement transition."""
        target_bounds = (
            transition.after_surface_bounds
            if use_after
            else transition.before_surface_bounds
        )
        pixels = transition.after_pixels if use_after else transition.before_pixels
        surface.set_bounds(target_bounds)
        overlap = transition.patch_bounds.intersection(target_bounds)
        if overlap is None:
            return True
        source = _region(pixels, transition.patch_bounds, overlap)
        return surface.restore_patch(overlap, source)

    def place(
        self,
        surface: ColorRasterSurface,
        fragment: RasterPixelFragment,
        destination_bounds: RasterBounds,
    ) -> RasterPixelTransition | None:
        """Composite one premultiplied fragment without modifying its source."""
        surface_bounds = surface.bounds
        if (
            fragment.pixel_format is not RasterPixelFormat.PREMULTIPLIED_ARGB32
            or destination_bounds.width != fragment.bounds.width
            or destination_bounds.height != fragment.bounds.height
        ):
            return None
        after_bounds = (
            surface_bounds
            if surface.extent_policy is RasterExtentPolicy.FIXED
            else surface_bounds.united(destination_bounds)
        )
        patch_bounds = destination_bounds.intersection(after_bounds)
        if patch_bounds is None:
            return None
        before = surface.capture_region(patch_bounds)
        after = np.array(before, copy=True)
        source_region = RasterBounds(
            patch_bounds.x - destination_bounds.x,
            patch_bounds.y - destination_bounds.y,
            patch_bounds.width,
            patch_bounds.height,
        )
        fragment_array_bounds = RasterBounds(
            0,
            0,
            fragment.bounds.width,
            fragment.bounds.height,
        )
        raw_source = _region(fragment.pixels, fragment_array_bounds, source_region)
        selection = _region(
            fragment.contribution_coverage.pixels,
            fragment_array_bounds,
            source_region,
        ).astype(np.uint16)[:, :, np.newaxis]
        source = (raw_source.astype(np.uint16) * selection + 127) // 255
        inverse_alpha = 255 - source[:, :, 3:4]
        replacement = source + (after.astype(np.uint16) * inverse_alpha + 127) // 255
        np.copyto(after, np.minimum(replacement, 255).astype(np.uint8))
        if np.array_equal(before, after) and after_bounds == surface_bounds:
            return None
        transition = RasterPixelTransition._adopt_detached(
            patch_bounds,
            surface_bounds,
            after_bounds,
            before,
            after,
        )
        return transition if self.restore(surface, transition, use_after=True) else None


def _coverage_region(
    coverage: CoverageSnapshot,
    bounds: RasterBounds,
) -> np.ndarray:
    """Return coverage pixels aligned to contained local bounds."""
    source = coverage.bounds
    if source is None:
        return np.zeros((0, 0), dtype=np.uint8)
    relative = RasterBounds(
        bounds.x - source.x,
        bounds.y - source.y,
        bounds.width,
        bounds.height,
    )
    source_array_bounds = RasterBounds(0, 0, source.width, source.height)
    return _region(coverage.pixels, source_array_bounds, relative)


def _region(
    pixels: np.ndarray,
    pixel_bounds: RasterBounds,
    region: RasterBounds,
) -> np.ndarray:
    """Return one contained local-coordinate array view."""
    x = region.x - pixel_bounds.x
    y = region.y - pixel_bounds.y
    return pixels[y : y + region.height, x : x + region.width]
