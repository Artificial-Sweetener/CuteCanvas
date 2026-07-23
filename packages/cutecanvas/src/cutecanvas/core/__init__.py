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
"""CuteCanvas feature-installation and tool hook contracts."""

from qpane.sdk.overlays import OverlayDrawFn, SceneOverlayDrawFn

from .fallbacks import FeatureFailure, FeatureFallbacks
from .feature_coordinator import FeatureCoordinator
from .hooks import CursorProvider, CuteCanvasHooks, ToolFactory, ToolSignalBinder
from .state import CuteCanvasState

__all__ = [
    "CursorProvider",
    "CuteCanvasHooks",
    "CuteCanvasState",
    "FeatureCoordinator",
    "FeatureFailure",
    "FeatureFallbacks",
    "OverlayDrawFn",
    "SceneOverlayDrawFn",
    "ToolFactory",
    "ToolSignalBinder",
]
