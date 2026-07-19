#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Source-neutral coordination for composition editor interactions."""

from .floating_layers import FloatingLayerPromotionRegistry
from .interaction import EditorInteractionCoordinator
from .movement import EditorMovementInteraction
from .pixel_movement import SelectedPixelMovementController
from .selection_projection import LayerSelectionProjectionCache

__all__ = [
    "EditorInteractionCoordinator",
    "EditorMovementInteraction",
    "FloatingLayerPromotionRegistry",
    "LayerSelectionProjectionCache",
    "SelectedPixelMovementController",
]
