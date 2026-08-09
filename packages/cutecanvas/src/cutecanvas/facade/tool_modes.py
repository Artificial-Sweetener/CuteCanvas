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
"""Stable built-in tool-mode values exposed by the CuteCanvas facade."""

from ..tools import Tools
from ..vector.node_tool import VECTOR_NODE_MODE
from ..vector.text_tool import VECTOR_TEXT_MODE
from ..vector.tools import VECTOR_PATH_MODE, VECTOR_SHAPE_MODE


class CanvasToolModesMixin:
    """Expose built-in tool identifiers without owning tool lifecycle."""

    CONTROL_MODE_PANZOOM = Tools.CONTROL_MODE_PANZOOM
    CONTROL_MODE_CURSOR = Tools.CONTROL_MODE_CURSOR
    CONTROL_MODE_MOVE = Tools.CONTROL_MODE_MOVE
    CONTROL_MODE_TRANSFORM = Tools.CONTROL_MODE_TRANSFORM
    CONTROL_MODE_SHARED_EDGE_RESIZE = Tools.CONTROL_MODE_SHARED_EDGE_RESIZE
    CONTROL_MODE_DRAW_BRUSH = Tools.CONTROL_MODE_DRAW_BRUSH
    CONTROL_MODE_ERASER = Tools.CONTROL_MODE_ERASER
    CONTROL_MODE_CLONE_STAMP = Tools.CONTROL_MODE_CLONE_STAMP
    CONTROL_MODE_PAINT_BUCKET = Tools.CONTROL_MODE_PAINT_BUCKET
    CONTROL_MODE_SMART_SELECT = Tools.CONTROL_MODE_SMART_SELECT
    CONTROL_MODE_SMART_MASK = Tools.CONTROL_MODE_SMART_MASK
    CONTROL_MODE_SELECT_RECTANGLE = Tools.CONTROL_MODE_SELECT_RECTANGLE
    CONTROL_MODE_SELECT_ELLIPSE = Tools.CONTROL_MODE_SELECT_ELLIPSE
    CONTROL_MODE_SELECT_LASSO = Tools.CONTROL_MODE_SELECT_LASSO
    CONTROL_MODE_SELECT_POLYGON = Tools.CONTROL_MODE_SELECT_POLYGON
    CONTROL_MODE_MASK_RECTANGLE = Tools.CONTROL_MODE_MASK_RECTANGLE
    CONTROL_MODE_MASK_ELLIPSE = Tools.CONTROL_MODE_MASK_ELLIPSE
    CONTROL_MODE_MASK_LASSO = Tools.CONTROL_MODE_MASK_LASSO
    CONTROL_MODE_MASK_POLYGON = Tools.CONTROL_MODE_MASK_POLYGON
    CONTROL_MODE_VECTOR_SHAPE = VECTOR_SHAPE_MODE
    CONTROL_MODE_VECTOR_PATH = VECTOR_PATH_MODE
    CONTROL_MODE_VECTOR_NODE = VECTOR_NODE_MODE
    CONTROL_MODE_VECTOR_TEXT = VECTOR_TEXT_MODE


__all__ = ["CanvasToolModesMixin"]
