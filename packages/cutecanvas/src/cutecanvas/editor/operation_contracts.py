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
"""Value contracts for source-neutral editor operation decisions."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum

from .pixel_move_target import SelectedPixelMoveTarget


class EditorOperation(str, Enum):
    """Identify one source-neutral editor intent."""

    MOVE = "move"
    TRANSFORM = "transform"
    PAINT = "paint"
    DELETE_PIXELS = "delete-pixels"
    SELECT_PIXELS = "select-pixels"


class EditorOperationTarget(str, Enum):
    """Identify the semantic target chosen for an editor operation."""

    FLOATING_PIXELS = "floating-pixels"
    SELECTED_PIXELS = "selected-pixels"
    LAYER = "layer"
    PIXEL_SELECTION = "pixel-selection"
    DEFAULT_PAINT_TARGET = "default-paint-target"


class EditorOperationDenial(str, Enum):
    """Explain why an editor intent cannot currently execute."""

    NONE = "none"
    NO_ACTIVE_SCENE = "no-active-scene"
    NO_SELECTED_LAYER = "no-selected-layer"
    NO_PIXEL_SELECTION = "no-pixel-selection"
    NO_SELECTED_PIXELS = "no-selected-pixels"
    FLOATING_PIXELS_ACTIVE = "floating-pixels-active"
    POINTER_OUTSIDE_SELECTION = "pointer-outside-selection"
    DIRECT_PIXEL_EDIT_UNSUPPORTED = "direct-pixel-edit-unsupported"
    HOST_POLICY_DENIED = "host-policy-denied"
    LAYER_NOT_SELECTABLE = "layer-not-selectable"
    LAYER_NOT_MOVABLE = "layer-not-movable"
    INVALID_LAYER_GEOMETRY = "invalid-layer-geometry"
    NOTHING_TO_TRANSFORM = "nothing-to-transform"
    SOURCE_UNAVAILABLE = "source-unavailable"


class EditorOperationAlternative(str, Enum):
    """Describe an explicit non-destructive alternative to a denied intent."""

    RASTERIZE = "rasterize"
    EDIT_CONTENTS = "edit-contents"
    NEW_RASTER_LAYER = "new-raster-layer"


@dataclass(frozen=True, slots=True)
class EditorOperationResolution:
    """Carry one complete operation decision for tools, commands, and UI."""

    operation: EditorOperation
    allowed: bool
    target: EditorOperationTarget | None = None
    scene_id: uuid.UUID | None = None
    layer_id: uuid.UUID | None = None
    denial: EditorOperationDenial = EditorOperationDenial.NONE
    alternatives: tuple[EditorOperationAlternative, ...] = ()
    selected_pixels: SelectedPixelMoveTarget | None = None
