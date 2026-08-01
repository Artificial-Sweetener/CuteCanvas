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

"""Convert derived Qt paths into retained QPane vector geometry."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QPointF
from PySide6.QtGui import QPainterPath
from qpane.sdk.scene import LayerTransform
from qpane.sdk.vector import (
    VectorObject,
    VectorObjectKind,
    VectorPathCommand,
    VectorPathCommandKind,
    VectorStyle,
)

_CLOSE_TOLERANCE = 1e-7


def retained_vector_path(
    path: QPainterPath,
    *,
    style: VectorStyle,
    object_id: uuid.UUID | None = None,
) -> VectorObject | None:
    """Return retained vector geometry for one non-empty derived path."""
    if path.isEmpty():
        return None
    commands = _path_commands(path)
    bounds = path.boundingRect()
    if not commands or bounds.isEmpty():
        return None
    return VectorObject(
        object_id=object_id or uuid.uuid4(),
        kind=VectorObjectKind.PATH,
        local_bounds=(bounds.x(), bounds.y(), bounds.width(), bounds.height()),
        transform=LayerTransform(),
        style=style,
        path=commands,
    )


def _path_commands(path: QPainterPath) -> tuple[VectorPathCommand, ...]:
    """Translate Qt path elements into QPane's serializable commands."""
    commands: list[VectorPathCommand] = []
    subpath_start: QPointF | None = None
    index = 0
    count = path.elementCount()
    while index < count:
        element = path.elementAt(index)
        point = QPointF(element.x, element.y)
        if element.isMoveTo():
            subpath_start = point
            commands.append(VectorPathCommand(VectorPathCommandKind.MOVE, (point,)))
            index += 1
            continue
        if element.isLineTo():
            next_is_subpath = index + 1 == count or path.elementAt(index + 1).isMoveTo()
            if (
                subpath_start is not None
                and next_is_subpath
                and _same_point(point, subpath_start)
            ):
                commands.append(VectorPathCommand(VectorPathCommandKind.CLOSE))
            else:
                commands.append(VectorPathCommand(VectorPathCommandKind.LINE, (point,)))
            index += 1
            continue
        if element.isCurveTo() and index + 2 < count:
            control_two = path.elementAt(index + 1)
            endpoint = path.elementAt(index + 2)
            commands.append(
                VectorPathCommand(
                    VectorPathCommandKind.CUBIC,
                    (
                        point,
                        QPointF(control_two.x, control_two.y),
                        QPointF(endpoint.x, endpoint.y),
                    ),
                )
            )
            index += 3
            continue
        index += 1
    return tuple(commands)


def _same_point(first: QPointF, second: QPointF) -> bool:
    """Return whether two derived points encode the same closure point."""
    return (
        abs(first.x() - second.x()) <= _CLOSE_TOLERANCE
        and abs(first.y() - second.y()) <= _CLOSE_TOLERANCE
    )
