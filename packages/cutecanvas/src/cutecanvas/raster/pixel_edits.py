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
"""Editable-raster implementation of generic scene-layer pixel mutation."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from cutecanvas.coverage import CoverageSnapshot
from cutecanvas.scene.pixel_extraction import build_pixel_lift
from cutecanvas.scene.pixel_fragments import (
    RasterPixelFormat,
    RasterPixelFragment,
    RasterPixelLift,
)
from cutecanvas.scene.pixel_transitions import RasterPixelTransition
from cutecanvas.types import RasterExtentPolicy
from qpane.sdk.scene import LayerDescriptor, RasterBounds, SceneDescriptor

from ..resources import ProjectResourceReference
from .assets import EditableRasterAssetStore
from .pixel_translation import ColorPixelTranslator


class EditableRasterPixelMutationOwner:
    """Apply selection-constrained transparency edits to color raster assets."""

    def __init__(
        self,
        assets: EditableRasterAssetStore,
        changed: Callable[[RasterBounds], None],
        structure_changed: Callable[[], None] | None = None,
    ) -> None:
        """Bind authoritative assets and render invalidation callback."""
        self._assets = assets
        self._changed = changed
        self._structure_changed = structure_changed
        self._translator = ColorPixelTranslator()

    def supports_layer(self, scene: SceneDescriptor, layer: LayerDescriptor) -> bool:
        """Return whether ``layer`` references an editable raster asset."""
        return self._asset(layer) is not None

    def extent_policy(self, layer: LayerDescriptor) -> RasterExtentPolicy | None:
        """Return the color surface's authoritative extent policy."""
        asset = self._asset(layer)
        return None if asset is None else asset.surface.extent_policy

    def revision_token(self, layer: LayerDescriptor) -> object | None:
        """Return the synchronized color-surface revision tuple."""
        asset = self._asset(layer)
        return None if asset is None else asset.surface.revisions()

    def content_coverage(
        self,
        layer: LayerDescriptor,
        bounds: RasterBounds,
    ) -> CoverageSnapshot | None:
        """Return alpha-supported occupancy without attenuating source alpha."""
        asset = self._asset(layer)
        if asset is None:
            return None
        overlap = asset.surface.bounds.intersection(bounds)
        if overlap is None:
            return None
        occupancy = asset.surface.capture_alpha_occupancy(overlap)
        if occupancy is None:
            return None
        return CoverageSnapshot._adopt_detached(
            overlap,
            asset.surface.extent_policy,
            occupancy,
        )

    def content_bounds(self, layer: LayerDescriptor) -> RasterBounds | None:
        """Return cached alpha-supported source-local bounds."""
        asset = self._asset(layer)
        return None if asset is None else asset.surface.content_bounds()

    def capture_patch(
        self,
        layer: LayerDescriptor,
        bounds: RasterBounds,
    ) -> np.ndarray | None:
        """Return detached BGRA pixels for one source-local patch."""
        asset = self._asset(layer)
        return None if asset is None else asset.surface.capture_patch(bounds)

    def clear_coverage(
        self,
        layer: LayerDescriptor,
        coverage: CoverageSnapshot,
    ) -> bool:
        """Multiply premultiplied color and alpha by inverse soft coverage."""
        asset = self._asset(layer)
        bounds = coverage.bounds
        if asset is None or bounds is None:
            return False
        inverse = 255 - coverage.pixels.astype(np.uint16)

        def clear(pixels: np.ndarray) -> bool:
            """Apply destination-out alpha while preserving premultiplication."""
            replacement = (
                pixels.astype(np.uint16) * inverse[:, :, np.newaxis] + 127
            ) // 255
            result = replacement.astype(np.uint8)
            if np.array_equal(pixels, result):
                return False
            np.copyto(pixels, result)
            return True

        changed = asset.surface.mutate_patch(bounds, clear)
        if changed:
            self._changed(bounds)
        return changed

    def restore_patch(
        self,
        layer: LayerDescriptor,
        bounds: RasterBounds,
        pixels: np.ndarray,
    ) -> bool:
        """Restore a detached BGRA patch for undo or redo."""
        asset = self._asset(layer)
        if asset is None or not asset.surface.restore_patch(bounds, pixels):
            return False
        self._changed(bounds)
        return True

    def finalize_patch_edit(self, layer: LayerDescriptor) -> None:
        """Keep color-raster storage governed by its existing surface policy."""

    def lift_coverage(
        self,
        layer: LayerDescriptor,
        coverage: CoverageSnapshot,
    ) -> RasterPixelLift | None:
        """Capture contributing color samples and source clearing without mutation."""
        asset = self._asset(layer)
        bounds = coverage.bounds
        if asset is None or bounds is None or not asset.surface.bounds.contains(bounds):
            return None
        pixels = asset.surface.capture_patch(bounds)
        if pixels is None:
            return None
        return build_pixel_lift(
            source_pixels=pixels,
            coverage=coverage,
            pixel_format=RasterPixelFormat.PREMULTIPLIED_ARGB32,
            surface_bounds=asset.surface.bounds,
        )

    def preview_move(
        self,
        layer: LayerDescriptor,
        lift: RasterPixelLift,
        delta_x: int,
        delta_y: int,
        *,
        cut_source: bool,
    ) -> RasterPixelTransition | None:
        """Compose an exact color transition without mutating the asset."""
        asset = self._asset(layer)
        if (
            asset is None
            or lift.fragment.pixel_format is not RasterPixelFormat.PREMULTIPLIED_ARGB32
        ):
            return None
        return self._translator.preview_fragment_move(
            asset.surface,
            lift.fragment,
            delta_x,
            delta_y,
            cut_source=cut_source,
        )

    def place_fragment(
        self,
        layer: LayerDescriptor,
        fragment: RasterPixelFragment,
        destination: RasterBounds,
    ) -> RasterPixelTransition | None:
        """Composite one compatible color fragment into this raster."""
        asset = self._asset(layer)
        if asset is None:
            return None
        transition = self._translator.place(asset.surface, fragment, destination)
        if transition is not None:
            self._publish_transition(transition)
        return transition

    def accepts_fragment(
        self,
        layer: LayerDescriptor,
        fragment: RasterPixelFragment,
    ) -> bool:
        """Accept premultiplied fragments for owned editable color rasters."""
        return bool(
            self._asset(layer) is not None
            and fragment.pixel_format is RasterPixelFormat.PREMULTIPLIED_ARGB32
        )

    def transition_matches(
        self,
        layer: LayerDescriptor,
        transition: RasterPixelTransition,
        *,
        use_after: bool,
    ) -> bool:
        """Compare current color storage with one retained transition side."""
        asset = self._asset(layer)
        if asset is None:
            return False
        expected_bounds = (
            transition.after_surface_bounds
            if use_after
            else transition.before_surface_bounds
        )
        expected = transition.after_pixels if use_after else transition.before_pixels
        return bool(
            asset.surface.bounds == expected_bounds
            and np.array_equal(
                asset.surface.capture_region(transition.patch_bounds),
                expected,
            )
        )

    def restore_transition(
        self,
        layer: LayerDescriptor,
        transition: RasterPixelTransition,
        *,
        use_after: bool,
    ) -> bool:
        """Restore one color transition and synchronize presentation."""
        asset = self._asset(layer)
        if asset is None or not self._translator.restore(
            asset.surface,
            transition,
            use_after=use_after,
        ):
            return False
        self._publish_transition(transition)
        return True

    def _publish_transition(self, transition: RasterPixelTransition) -> None:
        """Publish pixel and optional structure changes exactly once."""
        self._changed(transition.patch_bounds)
        if (
            transition.before_surface_bounds != transition.after_surface_bounds
            and self._structure_changed is not None
        ):
            self._structure_changed()

    def _asset(self, layer: LayerDescriptor):
        """Resolve the editable raster asset referenced by ``layer``."""
        source = layer.source
        return (
            None
            if not isinstance(source, ProjectResourceReference)
            else self._assets.get(source.resource_id)
        )
