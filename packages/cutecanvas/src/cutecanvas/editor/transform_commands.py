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
"""Resolve discrete affine commands into exact scene-space deltas."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF

from cutecanvas.types import EditorTransformCommand
from qpane.sdk.scene import LayerTransform, TransformOperation


def command_transform(
    command: EditorTransformCommand,
    center: QPointF,
) -> LayerTransform:
    """Build one scene-space affine delta around a detached frame center."""
    if command is EditorTransformCommand.FLIP_HORIZONTAL:
        linear = (-1.0, 0.0, 0.0, 1.0)
    elif command is EditorTransformCommand.FLIP_VERTICAL:
        linear = (1.0, 0.0, 0.0, -1.0)
    else:
        angle = -90.0 if command is EditorTransformCommand.ROTATE_LEFT_90 else 90.0
        radians = math.radians(angle)
        cosine = round(math.cos(radians), 15)
        sine = round(math.sin(radians), 15)
        linear = (cosine, sine, -sine, cosine)
    m11, m12, m21, m22 = linear
    return LayerTransform(
        m11,
        m12,
        m21,
        m22,
        center.x() - (m11 * center.x() + m21 * center.y()),
        center.y() - (m12 * center.x() + m22 * center.y()),
    )


def operation_label(operation: TransformOperation) -> str:
    """Return a concise history label for one settled pointer operation."""
    return operation.kind.value.replace("-", " ").title()


def command_label(command: EditorTransformCommand) -> str:
    """Return a concise history label for one discrete affine command."""
    return command.value.replace("-", " ").title()


__all__ = ["command_label", "command_transform", "operation_label"]
