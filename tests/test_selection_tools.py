#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Tests for geometric pixel-selection tools."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent

from qpane.coverage import CoverageCombineMode
from qpane.tools.ports import PixelSelectionInteractionPort
from qpane.tools.selection_shapes import (
    EllipseSelectionTool,
    LassoSelectionTool,
    RectangleSelectionTool,
)


def _event(
    event_type: QEvent.Type,
    point: QPointF,
    button: Qt.MouseButton,
    buttons: Qt.MouseButton,
) -> QMouseEvent:
    """Build a mouse event for one selection gesture."""
    return QMouseEvent(
        event_type,
        point,
        point,
        point,
        button,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )


def _drag(tool, points: list[QPointF]) -> None:
    """Deliver one press, zero or more moves, and a release."""
    tool.mousePressEvent(
        _event(
            QEvent.Type.MouseButtonPress,
            points[0],
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
    )
    for point in points[1:-1]:
        tool.mouseMoveEvent(
            _event(
                QEvent.Type.MouseMove,
                point,
                Qt.MouseButton.NoButton,
                Qt.MouseButton.LeftButton,
            )
        )
    tool.mouseReleaseEvent(
        _event(
            QEvent.Type.MouseButtonRelease,
            points[-1],
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )
    )


def test_rectangle_tool_commits_scene_geometry_once() -> None:
    commits = []
    tool = RectangleSelectionTool()
    tool.activate(
        PixelSelectionInteractionPort(
            panel_to_scene_point=lambda point: point + QPointF(10.0, 20.0),
            commit_pixel_selection=lambda coverage, mode: commits.append(
                (coverage, mode)
            )
            or True,
        )
    )

    _drag(tool, [QPointF(1.0, 2.0), QPointF(6.0, 8.0)])

    assert len(commits) == 1
    assert commits[0][0].bounds.x == 11
    assert commits[0][0].bounds.y == 22
    assert commits[0][1] is CoverageCombineMode.REPLACE


def test_selection_modifiers_choose_add_subtract_and_intersect() -> None:
    modifier = {"shift": False, "alt": False}
    modes = []
    tool = EllipseSelectionTool()
    tool.activate(
        PixelSelectionInteractionPort(
            panel_to_scene_point=lambda point: point,
            is_shift_held=lambda: modifier["shift"],
            is_alt_held=lambda: modifier["alt"],
            commit_pixel_selection=lambda _coverage, mode: modes.append(mode) or True,
        )
    )

    for shift, alt in ((True, False), (False, True), (True, True)):
        modifier.update(shift=shift, alt=alt)
        _drag(tool, [QPointF(), QPointF(10.0, 10.0)])

    assert modes == [
        CoverageCombineMode.ADD,
        CoverageCombineMode.SUBTRACT,
        CoverageCombineMode.INTERSECT,
    ]


def test_lasso_requires_area_and_commits_accumulated_points() -> None:
    commits = []
    tool = LassoSelectionTool()
    tool.activate(
        PixelSelectionInteractionPort(
            panel_to_scene_point=lambda point: point,
            commit_pixel_selection=lambda coverage, mode: commits.append(
                (coverage, mode)
            )
            or True,
        )
    )

    _drag(tool, [QPointF(), QPointF(5.0, 0.0)])
    assert not commits

    _drag(
        tool,
        [QPointF(), QPointF(8.0, 1.0), QPointF(5.0, 8.0), QPointF(1.0, 5.0)],
    )
    assert len(commits) == 1
    assert commits[0][0].pixels.max() == 255


def test_escape_cancels_active_geometry_without_committing() -> None:
    """Escape should dismiss only the transient selection gesture."""
    commits = []
    tool = RectangleSelectionTool()
    tool.activate(
        PixelSelectionInteractionPort(
            panel_to_scene_point=lambda point: point,
            commit_pixel_selection=lambda coverage, mode: commits.append(
                (coverage, mode)
            )
            or True,
        )
    )
    tool.mousePressEvent(
        _event(
            QEvent.Type.MouseButtonPress,
            QPointF(2.0, 3.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
    )
    tool.mouseMoveEvent(
        _event(
            QEvent.Type.MouseMove,
            QPointF(20.0, 30.0),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
        )
    )

    escape = QKeyEvent(QEvent.Type.KeyPress, Qt.Key_Escape, Qt.NoModifier)
    tool.keyPressEvent(escape)
    tool.mouseReleaseEvent(
        _event(
            QEvent.Type.MouseButtonRelease,
            QPointF(20.0, 30.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )
    )

    assert escape.isAccepted()
    assert not commits
