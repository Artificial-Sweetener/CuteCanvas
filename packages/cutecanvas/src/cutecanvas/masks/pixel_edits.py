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
"""Mask-domain implementation of generic scene-layer pixel edits."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Protocol

import numpy as np
from cutecanvas.coverage import CoverageCombineMode, CoverageSnapshot, combine_coverage
from cutecanvas.scene.pixel_extraction import build_pixel_lift
from cutecanvas.scene.pixel_fragments import (
    RasterPixelFormat,
    RasterPixelFragment,
    RasterPixelLift,
)
from cutecanvas.scene.pixel_transitions import RasterPixelTransition
from cutecanvas.types import RasterExtentPolicy
from PySide6.QtCore import QRect
from PySide6.QtGui import QImage
from qpane.sdk.scene import LayerDescriptor, RasterBounds, SceneDescriptor

from ..resources import ProjectResourceReference
from .mask import MaskLayer
from .pixel_translation import MaskPixelTranslator


class MaskPixelAssetLookup(Protocol):
    """Resolve authoritative mask layers for generic pixel editing."""

    def get_layer(self, mask_id: uuid.UUID) -> MaskLayer | None:
        """Return one mask asset when it exists."""
        ...

    def touch(self, mask_id: uuid.UUID) -> None:
        """Advance the shared project-resource revision after direct mutation."""
        ...


class MaskPixelRenderSynchronizer:
    """Invalidate derived mask products after durable local pixel mutations."""

    def __init__(
        self,
        assets: MaskPixelAssetLookup,
        invalidate_region: Callable[[QRect, MaskLayer], None],
    ) -> None:
        """Bind authoritative storage and durable render invalidation."""
        self._assets = assets
        self._invalidate_region = invalidate_region

    def refresh(self, mask_id: uuid.UUID, local_bounds: RasterBounds) -> None:
        """Invalidate derived products intersecting one durable local mutation."""
        layer = self._assets.get_layer(mask_id)
        if layer is None:
            return
        storage_bounds = layer.coverage.raster.storage_rect(local_bounds)
        if storage_bounds is None:
            return
        self._invalidate_region(storage_bounds.to_qrect(), layer)


class MaskLayerPixelMutationOwner:
    """Apply selection-constrained patches to authoritative mask coverage."""

    def __init__(
        self,
        assets: MaskPixelAssetLookup,
        changed: Callable[[uuid.UUID, RasterBounds], None],
        structure_changed: Callable[[], None] | None = None,
    ) -> None:
        """Bind mask assets and their render invalidation callback."""
        self._assets = assets
        self._changed = changed
        self._structure_changed = structure_changed
        self._translator = MaskPixelTranslator()

    def supports_layer(self, scene: SceneDescriptor, layer: LayerDescriptor) -> bool:
        """Return whether ``layer`` references a mask asset owned here."""
        return (
            isinstance(layer.source, ProjectResourceReference)
            and self._assets.get_layer(layer.source.resource_id) is not None
        )

    def extent_policy(self, layer: LayerDescriptor) -> RasterExtentPolicy | None:
        """Return the mask surface's authoritative extent policy."""
        mask = self._mask_layer(layer)
        return None if mask is None else mask.coverage.raster.extent_policy

    def revision_token(self, layer: LayerDescriptor) -> object | None:
        """Return the synchronized coverage-surface revision tuple."""
        mask = self._mask_layer(layer)
        return None if mask is None else mask.coverage.raster.revisions()

    def content_coverage(
        self,
        layer: LayerDescriptor,
        bounds: RasterBounds,
    ) -> CoverageSnapshot | None:
        """Return occupancy for painted mask values while preserving soft pixels."""
        mask = self._mask_layer(layer)
        surface_bounds = None if mask is None else mask.coverage.raster.bounds
        overlap = (
            None if surface_bounds is None else surface_bounds.intersection(bounds)
        )
        if mask is None or overlap is None:
            return None
        storage = mask.coverage.raster.storage_rect(overlap)
        if storage is None:
            return None
        pixels = mask.coverage.raster.snapshot_storage_region(storage)
        occupancy = np.where(pixels != 0, np.uint8(255), np.uint8(0))
        return CoverageSnapshot._adopt_detached(
            overlap,
            mask.coverage.raster.extent_policy,
            occupancy,
        )

    def content_bounds(self, layer: LayerDescriptor) -> RasterBounds | None:
        """Return cached nonzero mask bounds in source-local coordinates."""
        mask = self._mask_layer(layer)
        return None if mask is None else mask.coverage.content_bounds()

    def capture_patch(
        self,
        layer: LayerDescriptor,
        bounds: RasterBounds,
    ) -> np.ndarray | None:
        """Return detached mask pixels for one local patch."""
        mask = self._mask_layer(layer)
        if mask is None:
            return None
        storage = mask.coverage.raster.storage_rect(bounds)
        if (
            storage is None
            or storage.width != bounds.width
            or storage.height != bounds.height
        ):
            return None
        return mask.coverage.raster.snapshot_storage_region(storage)

    def clear_coverage(
        self,
        layer: LayerDescriptor,
        coverage: CoverageSnapshot,
    ) -> bool:
        """Subtract local soft selection coverage from mask pixels."""
        bounds = coverage.bounds
        mask = self._mask_layer(layer)
        if bounds is None or mask is None:
            return False
        storage = mask.coverage.raster.storage_rect(bounds)
        if storage is None or coverage.pixels.shape != (storage.height, storage.width):
            return False
        current = mask.coverage.raster.snapshot_storage_region(storage)
        replacement = combine_coverage(
            current,
            coverage.pixels,
            CoverageCombineMode.SUBTRACT,
        )
        if np.array_equal(current, replacement):
            return False

        def mutate(destination: np.ndarray, _image: QImage) -> None:
            """Apply destination-out coverage to the canonical mask patch."""
            np.copyto(destination, replacement)

        mask.coverage.raster.mutate_storage_region(storage, mutate)
        self._assets.touch(mask.mask_id)
        self._changed(mask.mask_id, bounds)
        return True

    def restore_patch(
        self,
        layer: LayerDescriptor,
        bounds: RasterBounds,
        pixels: np.ndarray,
    ) -> bool:
        """Restore one detached mask patch for undo or redo."""
        mask = self._mask_layer(layer)
        if mask is None:
            return False
        mask.coverage.raster.ensure_writable(bounds)
        storage = mask.coverage.raster.storage_rect(bounds)
        if storage is None or pixels.shape != (storage.height, storage.width):
            return False

        def mutate(destination: np.ndarray, _image: QImage) -> None:
            """Copy retained patch pixels into canonical mask storage."""
            np.copyto(destination, pixels)

        mask.coverage.raster.mutate_storage_region(storage, mutate)
        self._assets.touch(mask.mask_id)
        self._changed(mask.mask_id, bounds)
        return True

    def finalize_patch_edit(self, layer: LayerDescriptor) -> None:
        """Fit expandable mask allocation after the edit's patch is captured."""
        mask = self._mask_layer(layer)
        if mask is not None and mask.coverage.compact_raster_storage():
            self._assets.touch(mask.mask_id)
            if self._structure_changed is not None:
                self._structure_changed()

    def lift_coverage(
        self,
        layer: LayerDescriptor,
        coverage: CoverageSnapshot,
    ) -> RasterPixelLift | None:
        """Capture contributing mask values and source clearing without mutation."""
        mask = self._mask_layer(layer)
        bounds = coverage.bounds
        surface_bounds = None if mask is None else mask.coverage.raster.bounds
        if (
            mask is None
            or bounds is None
            or surface_bounds is None
            or not surface_bounds.contains(bounds)
        ):
            return None
        storage = mask.coverage.raster.storage_rect(bounds)
        if storage is None:
            return None
        pixels = mask.coverage.raster.snapshot_storage_region(storage)
        return build_pixel_lift(
            source_pixels=pixels,
            coverage=coverage,
            pixel_format=RasterPixelFormat.COVERAGE8,
            surface_bounds=surface_bounds,
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
        """Compose an exact mask transition without mutating the asset."""
        mask = self._mask_layer(layer)
        if (
            mask is None
            or lift.fragment.pixel_format is not RasterPixelFormat.COVERAGE8
        ):
            return None
        return self._translator.preview_fragment_move(
            mask,
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
        """Composite one compatible scalar fragment into this mask."""
        mask = self._mask_layer(layer)
        if mask is None:
            return None
        transition = self._translator.place(mask, fragment, destination)
        if transition is not None:
            self._publish_transition(mask.mask_id, transition)
        return transition

    def accepts_fragment(
        self,
        layer: LayerDescriptor,
        fragment: RasterPixelFragment,
    ) -> bool:
        """Accept scalar fragments for owned editable mask surfaces."""
        return bool(
            self._mask_layer(layer) is not None
            and fragment.pixel_format is RasterPixelFormat.COVERAGE8
        )

    def transition_matches(
        self,
        layer: LayerDescriptor,
        transition: RasterPixelTransition,
        *,
        use_after: bool,
    ) -> bool:
        """Compare current scalar storage with one retained transition side."""
        mask = self._mask_layer(layer)
        surface_bounds = None if mask is None else mask.coverage.raster.bounds
        expected_bounds = (
            transition.after_surface_bounds
            if use_after
            else transition.before_surface_bounds
        )
        expected = transition.after_pixels if use_after else transition.before_pixels
        return bool(
            mask is not None
            and surface_bounds == expected_bounds
            and np.array_equal(
                _capture_mask_region(mask, transition.patch_bounds),
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
        """Restore one mask transition and synchronize derived rendering."""
        mask = self._mask_layer(layer)
        if mask is None or not self._translator.restore(
            mask,
            transition,
            use_after=use_after,
        ):
            return False
        self._publish_transition(mask.mask_id, transition)
        return True

    def _publish_transition(
        self,
        mask_id: uuid.UUID,
        transition: RasterPixelTransition,
    ) -> None:
        """Publish pixel and optional structure changes exactly once."""
        self._assets.touch(mask_id)
        self._changed(mask_id, transition.patch_bounds)
        if (
            transition.before_surface_bounds != transition.after_surface_bounds
            and self._structure_changed is not None
        ):
            self._structure_changed()

    def _mask_layer(self, layer: LayerDescriptor) -> MaskLayer | None:
        """Resolve the authoritative mask asset referenced by ``layer``."""
        source = layer.source
        return (
            None
            if not isinstance(source, ProjectResourceReference)
            else self._assets.get_layer(source.resource_id)
        )


def _capture_mask_region(mask: MaskLayer, bounds: RasterBounds) -> np.ndarray:
    """Return a zero-padded local mask region for transition validation."""
    pixels = np.zeros((bounds.height, bounds.width), dtype=np.uint8)
    surface_bounds = mask.coverage.raster.bounds
    overlap = None if surface_bounds is None else surface_bounds.intersection(bounds)
    if overlap is None:
        return pixels
    storage = mask.coverage.raster.storage_rect(overlap)
    if storage is None:
        return pixels
    source = mask.coverage.raster.snapshot_storage_region(storage)
    x = overlap.x - bounds.x
    y = overlap.y - bounds.y
    pixels[y : y + overlap.height, x : x + overlap.width] = source
    return pixels
