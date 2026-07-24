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
"""Document-owned replay of generic raster pixel history."""

from __future__ import annotations

import uuid
from collections.abc import Callable

import numpy as np
from qpane.sdk.scene import RasterBounds

from ..composition.layers import CompositionLayerStore
from ..editor.floating_history import LayerPixelTransition
from ..masks.mask import MaskAssetStore
from ..masks.pixel_translation import MaskPixelTranslator
from ..raster.assets import EditableRasterAssetStore
from ..raster.pixel_translation import ColorPixelTranslator
from ..scene.pixel_edits import RasterPixelEdit
from ..scene.pixel_transitions import RasterPixelTransition
from .model import ProjectResourceKind, ProjectResourceReference
from .store import ProjectResourceStore


class ResourcePixelHistoryOwner:
    """Replay retained patches directly through durable resource payload owners."""

    def __init__(
        self,
        *,
        resources: ProjectResourceStore,
        rasters: EditableRasterAssetStore,
        masks: MaskAssetStore,
        changed: Callable[[uuid.UUID, RasterBounds], None],
    ) -> None:
        """Bind resource identity, payload stores, and document invalidation."""
        self._resources = resources
        self._rasters = rasters
        self._masks = masks
        self._changed = changed

    def undo(self, command: object) -> bool:
        """Restore the retained before-patch."""
        return self._restore(command, use_after=False)

    def redo(self, command: object) -> bool:
        """Restore the retained after-patch."""
        return self._restore(command, use_after=True)

    def _restore(self, command: object, *, use_after: bool) -> bool:
        """Route one patch by authoritative resource kind."""
        if not isinstance(command, RasterPixelEdit) or not isinstance(
            command.source,
            ProjectResourceReference,
        ):
            return False
        resource_id = command.source.resource_id
        record = self._resources.get(resource_id)
        pixels = command.after if use_after else command.before
        if record is None:
            return False
        if record.kind is ProjectResourceKind.RASTER:
            asset = self._rasters.get(resource_id)
            changed = bool(
                asset is not None
                and asset.surface.restore_patch(command.bounds, pixels)
            )
        elif record.kind is ProjectResourceKind.COVERAGE:
            mask = self._masks.get_layer(resource_id)
            storage = (
                None
                if mask is None
                else mask.coverage.raster.storage_rect(command.bounds)
            )
            if (
                mask is None
                or storage is None
                or pixels.shape != (storage.height, storage.width)
            ):
                return False

            def restore(destination, _image) -> None:
                """Copy retained scalar coverage into sparse storage."""
                np.copyto(destination, pixels)

            mask.coverage.raster.mutate_storage_region(
                storage,
                restore,
            )
            self._masks.touch(resource_id)
            changed = True
        else:
            return False
        if changed:
            self._changed(resource_id, command.bounds)
        return changed


class ResourcePixelTransitionOwner:
    """Replay structure-aware movement transitions by durable layer resource."""

    def __init__(
        self,
        *,
        resources: ProjectResourceStore,
        layers: CompositionLayerStore,
        rasters: EditableRasterAssetStore,
        masks: MaskAssetStore,
        changed: Callable[[uuid.UUID, RasterBounds], None],
    ) -> None:
        """Bind durable layers, payload stores, and invalidation."""
        self._resources = resources
        self._layers = layers
        self._rasters = rasters
        self._masks = masks
        self._changed = changed
        self._color = ColorPixelTranslator()
        self._coverage = MaskPixelTranslator()

    def matches(
        self,
        item: LayerPixelTransition,
        *,
        use_after: bool,
    ) -> bool:
        """Return whether the current payload equals one transition side."""
        payload = self._payload(item)
        if payload is None:
            return False
        kind, value = payload
        transition = item.raster
        expected_bounds = _transition_bounds(transition, use_after=use_after)
        expected = _transition_pixels(transition, use_after=use_after)
        if kind is ProjectResourceKind.RASTER:
            return bool(
                value.surface.bounds == expected_bounds
                and np.array_equal(
                    value.surface.capture_region(transition.patch_bounds),
                    expected,
                )
            )
        return bool(
            value.coverage.raster.bounds == expected_bounds
            and np.array_equal(
                _capture_coverage_region(value, transition.patch_bounds),
                expected,
            )
        )

    def restore(
        self,
        item: LayerPixelTransition,
        *,
        use_after: bool,
    ) -> bool:
        """Restore one transition through its durable payload translator."""
        payload = self._payload(item)
        if payload is None:
            return False
        kind, value = payload
        transition = item.raster
        if kind is ProjectResourceKind.RASTER:
            changed = self._color.restore(
                value.surface,
                transition,
                use_after=use_after,
            )
            resource_id = value.raster_id
        else:
            changed = self._coverage.restore(
                value,
                transition,
                use_after=use_after,
            )
            resource_id = value.mask_id
            if changed:
                self._masks.touch(resource_id)
        if changed:
            self._changed(resource_id, transition.patch_bounds)
        return changed

    def _payload(self, item: LayerPixelTransition):
        """Resolve one transition's current resource kind and payload."""
        layer = self._layers.layer(item.scene_id, item.layer_id)
        if layer is None or not isinstance(layer.source, ProjectResourceReference):
            return None
        resource_id = layer.source.resource_id
        record = self._resources.get(resource_id)
        if record is None:
            return None
        if record.kind is ProjectResourceKind.RASTER:
            payload = self._rasters.get(resource_id)
        elif record.kind is ProjectResourceKind.COVERAGE:
            payload = self._masks.get_layer(resource_id)
        else:
            return None
        return None if payload is None else (record.kind, payload)


def _transition_bounds(
    transition: RasterPixelTransition,
    *,
    use_after: bool,
):
    """Return the expected surface bounds for one transition side."""
    return (
        transition.after_surface_bounds
        if use_after
        else transition.before_surface_bounds
    )


def _transition_pixels(
    transition: RasterPixelTransition,
    *,
    use_after: bool,
) -> np.ndarray:
    """Return retained pixels for one transition side."""
    return transition.after_pixels if use_after else transition.before_pixels


def _capture_coverage_region(mask, bounds) -> np.ndarray:
    """Return a zero-padded local coverage region for equality checks."""
    pixels = np.zeros((bounds.height, bounds.width), dtype=np.uint8)
    overlap = mask.coverage.raster.bounds.intersection(bounds)
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
