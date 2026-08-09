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
"""Atomic document geometry values and anchored canvas-bound edits."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from enum import Enum
from math import ceil, floor
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QRectF, QSize
from qpane.sdk.scene import (
    ClipCoordinateSpace,
    LayerClip,
    LayerSourceReference,
    LayerTransform,
    RasterBounds,
)

from ..composition import CompositionService
from ..composition.layers import CompositionLayerInstance
from ..composition.resource_references import instance_resources
from ..coverage import CoverageSnapshot
from ..coverage.document import CoverageDocument
from ..selection import PixelSelectionService

if TYPE_CHECKING:
    from .canvas_crop import CanvasCropOwner


class CanvasAnchor(str, Enum):
    """Select the canvas point that remains fixed during a bounds resize."""

    TOP_LEFT = "top-left"
    TOP = "top"
    TOP_RIGHT = "top-right"
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
    BOTTOM_LEFT = "bottom-left"
    BOTTOM = "bottom"
    BOTTOM_RIGHT = "bottom-right"


@dataclass(frozen=True, slots=True, eq=False)
class CanvasGeometryState:
    """Capture one composition's bounds, layers, and pixel selection."""

    bounds: QRectF
    layers: tuple[CompositionLayerInstance, ...]
    selection_document: CoverageDocument | None
    selection_coverage: CoverageSnapshot | None

    def __post_init__(self) -> None:
        """Detach mutable bounds and ordered layer state."""
        object.__setattr__(self, "bounds", QRectF(self.bounds))
        object.__setattr__(self, "layers", tuple(self.layers))

    def __eq__(self, other: object) -> bool:
        """Compare structural state and evaluated selection pixels exactly."""
        if not isinstance(other, CanvasGeometryState):
            return NotImplemented
        return (
            self.bounds == other.bounds
            and self.layers == other.layers
            and self.selection_document == other.selection_document
            and _coverage_equal(self.selection_coverage, other.selection_coverage)
        )


@dataclass(frozen=True, slots=True)
class CanvasGeometryEdit:
    """Retain one exact atomic canvas-geometry transition."""

    scope_id: uuid.UUID
    before: CanvasGeometryState
    after: CanvasGeometryState
    retained_payload_bytes: int = 0

    @property
    def retained_bytes(self) -> int:
        """Return structural history overhead excluding leased resources."""
        selection_bytes = sum(
            (
                0
                if state.selection_coverage is None
                else state.selection_coverage.pixels.nbytes
            )
            for state in (self.before, self.after)
        )
        return (
            512
            + 256 * (len(self.before.layers) + len(self.after.layers))
            + selection_bytes
            + self.retained_payload_bytes
        )

    @property
    def retained_resources(self) -> tuple[LayerSourceReference, ...]:
        """Retain every source reachable in either chronology direction."""
        return tuple(
            dict.fromkeys(
                source
                for state in (self.before, self.after)
                for layer in state.layers
                for source in instance_resources(layer)
            )
        )


class CanvasGeometryStateOwner:
    """Own capture and replay of composition-wide geometry state."""

    def __init__(
        self,
        compositions: CompositionService,
        selections: PixelSelectionService,
    ) -> None:
        """Bind the authoritative document state owners."""
        self._compositions = compositions
        self._selections = selections

    def capture(self, composition_id: uuid.UUID) -> CanvasGeometryState:
        """Return one detached current state snapshot."""
        selection = self._selections.state(composition_id)
        return CanvasGeometryState(
            self._compositions.record(composition_id).canvas_bounds,
            self._compositions.layers.layers_for_composition(composition_id),
            self._selections.document(composition_id),
            selection.coverage,
        )

    def restore(self, composition_id: uuid.UUID, state: CanvasGeometryState) -> bool:
        """Restore one validated state direction without recording history."""
        current = self.capture(composition_id)
        if current == state:
            return False
        try:
            layers_changed = self._compositions.layers.replace_layers(
                composition_id,
                state.layers,
            )
            bounds_changed = self._compositions.set_canvas_bounds(
                composition_id,
                state.bounds,
            )
            selection_changed = self._selections.restore_document(
                composition_id,
                state.selection_document,
                coverage=state.selection_coverage,
            )
        except Exception:
            self._compositions.layers.replace_layers(composition_id, current.layers)
            self._compositions.set_canvas_bounds(composition_id, current.bounds)
            self._selections.restore_document(
                composition_id,
                current.selection_document,
                coverage=current.selection_coverage,
            )
            raise
        return layers_changed or bounds_changed or selection_changed

    def undo(self, command: object) -> bool:
        """Restore the exact geometry before one canvas edit."""
        if not isinstance(command, CanvasGeometryEdit):
            return False
        return self.restore(command.scope_id, command.before)

    def redo(self, command: object) -> bool:
        """Restore the exact geometry after one canvas edit."""
        if not isinstance(command, CanvasGeometryEdit):
            return False
        return self.restore(command.scope_id, command.after)


class CanvasBoundsResizeOwner:
    """Apply lossless anchored canvas-bound changes through one history edit."""

    def __init__(
        self,
        state: CanvasGeometryStateOwner,
        compositions: CompositionService,
    ) -> None:
        """Bind geometry replay and chronological edit ownership."""
        self._state = state
        self._compositions = compositions

    def resize(
        self,
        composition_id: uuid.UUID,
        size: QSize,
        *,
        anchor: CanvasAnchor,
    ) -> bool:
        """Resize canvas bounds and translate content without resampling."""
        target = _validated_size(size)
        resolved_anchor = CanvasAnchor(anchor)
        before = self._state.capture(composition_id)
        old_width, old_height = _pixel_aligned_size(before.bounds)
        if target == QSize(old_width, old_height):
            return False
        delta_x, delta_y = _anchor_translation(
            target.width() - old_width,
            target.height() - old_height,
            resolved_anchor,
        )
        bounds = QRectF(
            before.bounds.x(),
            before.bounds.y(),
            float(target.width()),
            float(target.height()),
        )
        layers = tuple(
            replace(
                layer,
                transform=layer.transform.followed_by(
                    LayerTransform(dx=delta_x, dy=delta_y)
                ),
                clip=_translated_scene_clip(layer.clip, delta_x, delta_y),
            )
            for layer in before.layers
        )
        selection_document = _translated_coverage_document(
            before.selection_document,
            delta_x,
            delta_y,
        )
        selection_coverage = (
            None
            if before.selection_coverage is None
            else before.selection_coverage.translated(delta_x, delta_y)
        )
        after = CanvasGeometryState(
            bounds,
            layers,
            selection_document,
            selection_coverage,
        )
        if not self._state.restore(composition_id, after):
            return False
        self._compositions.edit_controller.record_applied(
            CanvasGeometryEdit(composition_id, before, after)
        )
        return True


@dataclass(frozen=True, slots=True)
class CanvasGeometryDomain:
    """Group cohesive document-owned canvas geometry operations."""

    state: CanvasGeometryStateOwner
    bounds: CanvasBoundsResizeOwner
    crop: CanvasCropOwner

    @classmethod
    def create(
        cls,
        compositions: CompositionService,
        selections: PixelSelectionService,
    ) -> CanvasGeometryDomain:
        """Construct geometry owners and install chronological replay."""
        from .canvas_crop import CanvasCropOwner

        state = CanvasGeometryStateOwner(compositions, selections)
        compositions.edit_controller.register_handler(
            CanvasGeometryEdit,
            undo=state.undo,
            redo=state.redo,
        )
        return cls(
            state,
            CanvasBoundsResizeOwner(state, compositions),
            CanvasCropOwner(state, compositions),
        )


def _validated_size(size: QSize) -> QSize:
    """Return a detached positive integer canvas size."""
    if not isinstance(size, QSize):
        raise TypeError("size must be a QSize")
    detached = QSize(size)
    if detached.width() <= 0 or detached.height() <= 0:
        raise ValueError("canvas dimensions must be positive")
    return detached


def scaled_raster_bounds(
    bounds: RasterBounds,
    scale: LayerTransform,
) -> RasterBounds:
    """Return the integer envelope of axis-aligned scaled raster bounds."""
    left = floor(bounds.x * scale.m11)
    top = floor(bounds.y * scale.m22)
    right = ceil(bounds.right * scale.m11)
    bottom = ceil(bounds.bottom * scale.m22)
    return RasterBounds(left, top, max(1, right - left), max(1, bottom - top))


def _pixel_aligned_size(bounds: QRectF) -> tuple[int, int]:
    """Return exact integer dimensions or reject subpixel canvas geometry."""
    width = round(bounds.width())
    height = round(bounds.height())
    if bounds.width() != float(width) or bounds.height() != float(height):
        raise ValueError("canvas bounds must have whole-pixel dimensions")
    return width, height


def _anchor_translation(
    delta_width: int,
    delta_height: int,
    anchor: CanvasAnchor,
) -> tuple[int, int]:
    """Return deterministic integer content translation for one anchor."""
    horizontal = {
        CanvasAnchor.TOP_LEFT: 0.0,
        CanvasAnchor.LEFT: 0.0,
        CanvasAnchor.BOTTOM_LEFT: 0.0,
        CanvasAnchor.TOP: 0.5,
        CanvasAnchor.CENTER: 0.5,
        CanvasAnchor.BOTTOM: 0.5,
        CanvasAnchor.TOP_RIGHT: 1.0,
        CanvasAnchor.RIGHT: 1.0,
        CanvasAnchor.BOTTOM_RIGHT: 1.0,
    }[anchor]
    vertical = {
        CanvasAnchor.TOP_LEFT: 0.0,
        CanvasAnchor.TOP: 0.0,
        CanvasAnchor.TOP_RIGHT: 0.0,
        CanvasAnchor.LEFT: 0.5,
        CanvasAnchor.CENTER: 0.5,
        CanvasAnchor.RIGHT: 0.5,
        CanvasAnchor.BOTTOM_LEFT: 1.0,
        CanvasAnchor.BOTTOM: 1.0,
        CanvasAnchor.BOTTOM_RIGHT: 1.0,
    }[anchor]
    return int(delta_width * horizontal), int(delta_height * vertical)


def _translated_scene_clip(
    clip: LayerClip | None,
    delta_x: int,
    delta_y: int,
) -> LayerClip | None:
    """Translate explicit scene clips while preserving relative clip policies."""
    if clip is None or clip.coordinate_space is not ClipCoordinateSpace.SCENE:
        return clip
    return LayerClip(
        clip.coordinate_space,
        clip.x + delta_x,
        clip.y + delta_y,
        clip.width,
        clip.height,
    )


def _translated_coverage_document(
    document: CoverageDocument | None,
    delta_x: int,
    delta_y: int,
) -> CoverageDocument | None:
    """Translate retained selection items without flattening authorship."""
    if document is None:
        return None
    translation = LayerTransform(dx=float(delta_x), dy=float(delta_y))
    return replace(
        document,
        items=tuple(
            replace(item, transform=item.transform.followed_by(translation))
            for item in document.items
        ),
        revision=document.revision + 1,
        evaluation_token=uuid.uuid4(),
    )


def _coverage_equal(
    left: CoverageSnapshot | None,
    right: CoverageSnapshot | None,
) -> bool:
    """Compare optional selection projections without ambiguous array equality."""
    if left is None or right is None:
        return left is right
    return (
        left.bounds == right.bounds
        and left.extent_policy is right.extent_policy
        and np.array_equal(left.pixels, right.pixels)
    )


__all__ = [
    "CanvasAnchor",
    "CanvasBoundsResizeOwner",
    "CanvasGeometryDomain",
    "CanvasGeometryEdit",
    "CanvasGeometryState",
    "CanvasGeometryStateOwner",
    "scaled_raster_bounds",
]
