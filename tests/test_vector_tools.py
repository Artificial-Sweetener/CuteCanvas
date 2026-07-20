#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Focused gesture tests for vector shape and path tools."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent

from qpane.tools.ports import VectorInteractionPort, VectorNodeInteractionPort
from qpane.vector.node_tool import VectorNodeTool
from qpane.vector.tools import VectorPathTool, VectorShapeTool


def _mouse(
    event_type: QEvent.Type,
    point: QPointF,
    button: Qt.MouseButton,
    buttons: Qt.MouseButton,
) -> QMouseEvent:
    """Build one detached local mouse event."""
    return QMouseEvent(
        event_type,
        point,
        point,
        point,
        button,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )


def test_shape_tool_commits_mapped_geometry_once() -> None:
    """Shape gestures should keep preview state transient and commit source points."""
    commits: list[tuple[QPointF, QPointF]] = []
    tool = VectorShapeTool()
    tool.activate(
        VectorInteractionPort(
            panel_to_source=lambda point: point + QPointF(10.0, 20.0),
            commit_shape=lambda begin, end: commits.append((begin, end)),
        )
    )
    tool.mousePressEvent(
        _mouse(
            QEvent.Type.MouseButtonPress,
            QPointF(2.0, 3.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
    )
    tool.mouseMoveEvent(
        _mouse(
            QEvent.Type.MouseMove,
            QPointF(8.0, 9.0),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
        )
    )
    tool.mouseReleaseEvent(
        _mouse(
            QEvent.Type.MouseButtonRelease,
            QPointF(12.0, 14.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )
    )

    assert commits == [(QPointF(12.0, 23.0), QPointF(22.0, 34.0))]


def test_shape_tool_escape_cancels_without_document_mutation() -> None:
    """Escape should discard only the unresolved shape gesture."""
    commits: list[object] = []
    tool = VectorShapeTool()
    tool.activate(
        VectorInteractionPort(
            panel_to_source=lambda point: point,
            commit_shape=lambda begin, end: commits.append((begin, end)),
        )
    )
    tool.mousePressEvent(
        _mouse(
            QEvent.Type.MouseButtonPress,
            QPointF(1.0, 1.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
    )
    escape = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.NoModifier)
    tool.keyPressEvent(escape)
    tool.mouseReleaseEvent(
        _mouse(
            QEvent.Type.MouseButtonRelease,
            QPointF(10.0, 10.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )
    )

    assert escape.isAccepted()
    assert commits == []


def test_path_tool_commits_explicit_nodes_with_enter() -> None:
    """Path clicks should remain transient until the explicit commit key."""
    commits: list[tuple[tuple[QPointF, ...], bool]] = []
    tool = VectorPathTool()
    tool.activate(
        VectorInteractionPort(
            panel_to_source=lambda point: point * 2.0,
            commit_path=lambda points, closed: commits.append((points, closed)),
        )
    )
    for point in (QPointF(1.0, 2.0), QPointF(4.0, 5.0), QPointF(7.0, 8.0)):
        tool.mousePressEvent(
            _mouse(
                QEvent.Type.MouseButtonPress,
                point,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
            )
        )
    enter = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.NoModifier)
    tool.keyPressEvent(enter)

    assert enter.isAccepted()
    assert commits == [
        (
            (QPointF(2.0, 4.0), QPointF(8.0, 10.0), QPointF(14.0, 16.0)),
            False,
        )
    ]


def test_node_tool_keeps_preview_in_domain_and_commits_once_on_release() -> None:
    """Direct selection should translate one captured drag through its focused port."""
    calls: list[tuple[str, QPointF | None]] = []
    tool = VectorNodeTool()
    tool.activate(
        VectorNodeInteractionPort(
            begin=lambda point: calls.append(("begin", point)) or True,
            update=lambda point: calls.append(("update", point)) or True,
            finish=lambda point: calls.append(("finish", point)) or True,
            cancel=lambda: calls.append(("cancel", None)) or True,
        )
    )
    tool.mousePressEvent(
        _mouse(
            QEvent.Type.MouseButtonPress,
            QPointF(2.0, 3.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
    )
    tool.mouseMoveEvent(
        _mouse(
            QEvent.Type.MouseMove,
            QPointF(8.0, 9.0),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
        )
    )
    tool.mouseReleaseEvent(
        _mouse(
            QEvent.Type.MouseButtonRelease,
            QPointF(12.0, 14.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )
    )

    assert calls == [
        ("begin", QPointF(2.0, 3.0)),
        ("update", QPointF(8.0, 9.0)),
        ("finish", QPointF(12.0, 14.0)),
    ]


def test_node_tool_escape_cancels_domain_preview() -> None:
    """Escape should explicitly cancel an unresolved node session."""
    cancelled: list[bool] = []
    tool = VectorNodeTool()
    tool.activate(
        VectorNodeInteractionPort(
            begin=lambda _point: True,
            cancel=lambda: cancelled.append(True) or True,
        )
    )
    tool.mousePressEvent(
        _mouse(
            QEvent.Type.MouseButtonPress,
            QPointF(2.0, 3.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
    )
    escape = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.NoModifier)
    tool.keyPressEvent(escape)

    assert escape.isAccepted()
    assert cancelled == [True]
