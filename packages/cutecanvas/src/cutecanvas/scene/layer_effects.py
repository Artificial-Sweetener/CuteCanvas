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
"""Construct CuteCanvas's always-on durable layer-effect registry."""

from qpane.sdk.scene import LayerEffectRenderRegistry

from ..document.canvas_crop import CanvasCropEffect, CanvasCropRenderOwner


def create_editor_layer_effects() -> LayerEffectRenderRegistry:
    """Return a registry with every always-on CuteCanvas effect owner."""
    registry = LayerEffectRenderRegistry()
    registry.register(CanvasCropEffect, CanvasCropRenderOwner())
    return registry


__all__ = ["create_editor_layer_effects"]
