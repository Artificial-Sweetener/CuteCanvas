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
"""Source-neutral coordination for composition editor interactions."""

from .floating_layers import FloatingLayerPromotionRegistry
from .interaction import EditorInteractionCoordinator
from .movement import EditorMovementInteraction
from .operation_resolution import (
    EditorOperation,
    EditorOperationAlternative,
    EditorOperationDenial,
    EditorOperationResolution,
    EditorOperationResolver,
    EditorOperationTarget,
)
from .paint_destination import InteractivePaintDestinationCoordinator
from .pixel_movement import SelectedPixelMovementController
from .policy import EditorPolicyController
from .selection_projection import LayerSelectionProjectionCache

__all__ = [
    "EditorInteractionCoordinator",
    "EditorMovementInteraction",
    "EditorOperation",
    "EditorOperationAlternative",
    "EditorOperationDenial",
    "EditorOperationResolution",
    "EditorOperationResolver",
    "EditorOperationTarget",
    "EditorPolicyController",
    "FloatingLayerPromotionRegistry",
    "InteractivePaintDestinationCoordinator",
    "LayerSelectionProjectionCache",
    "SelectedPixelMovementController",
]
