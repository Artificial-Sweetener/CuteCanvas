#    QPane + CuteCanvas - High-performance PySide6 rendering and editing
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
"""Tests for geometric pixel-selection tools."""

from __future__ import annotations

from cutecanvas.coverage import (
    CoverageCombineMode,
    CoverageDocument,
    CoverageDocumentEvaluator,
)
from cutecanvas.tools.ports import PixelSelectionInteractionPort
from cutecanvas.tools.selection_shapes import (
    EllipseSelectionTool,
    LassoSelectionTool,
    RectangleSelectionTool,
)
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent


def _event(
    event_type: QEvent.Type,
    point: QPointF,
    button: Qt.MouseButton,
    buttons: Qt.MouseButton,
    modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier,
) -> QMouseEvent:
    """Build a mouse event for one selection gesture."""
    return QMouseEvent(
        event_type,
        point,
        point,
        point,
        button,
        buttons,
        modifiers,
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
            commit_coverage_item=lambda item: commits.append(item) or True,
        )
    )

    _drag(tool, [QPointF(1.0, 2.0), QPointF(6.0, 8.0)])

    assert len(commits) == 1
    bounds = CoverageDocumentEvaluator().content_bounds(
        CoverageDocument().add(commits[0])
    )
    assert bounds is not None
    assert bounds.x == 11
    assert bounds.y == 22
    assert commits[0].combine_mode is CoverageCombineMode.REPLACE


def test_selection_modifiers_make_alt_subtractive_with_precedence() -> None:
    modifier = {"shift": False, "alt": False}
    modes = []
    tool = EllipseSelectionTool()
    tool.activate(
        PixelSelectionInteractionPort(
            panel_to_scene_point=lambda point: point,
            is_shift_held=lambda: modifier["shift"],
            is_alt_held=lambda: modifier["alt"],
            commit_coverage_item=lambda item: modes.append(item.combine_mode) or True,
        )
    )

    for shift, alt in ((True, False), (False, True), (True, True)):
        modifier.update(shift=shift, alt=alt)
        _drag(tool, [QPointF(), QPointF(10.0, 10.0)])

    assert modes == [
        CoverageCombineMode.ADD,
        CoverageCombineMode.SUBTRACT,
        CoverageCombineMode.SUBTRACT,
    ]


def test_lasso_requires_area_and_commits_accumulated_points() -> None:
    commits = []
    tool = LassoSelectionTool()
    tool.activate(
        PixelSelectionInteractionPort(
            panel_to_scene_point=lambda point: point,
            commit_coverage_item=lambda item: commits.append(item) or True,
        )
    )

    _drag(tool, [QPointF(), QPointF(5.0, 0.0)])
    assert not commits

    _drag(
        tool,
        [QPointF(), QPointF(8.0, 1.0), QPointF(5.0, 8.0), QPointF(1.0, 5.0)],
    )
    assert len(commits) == 1
    snapshot = CoverageDocumentEvaluator().rasterize(CoverageDocument().add(commits[0]))
    assert snapshot.pixels.max() == 255


def test_escape_cancels_active_geometry_without_committing() -> None:
    """Escape should dismiss only the transient selection gesture."""
    commits = []
    tool = RectangleSelectionTool()
    tool.activate(
        PixelSelectionInteractionPort(
            panel_to_scene_point=lambda point: point,
            commit_coverage_item=lambda item: commits.append(item) or True,
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


def test_shape_modifiers_constrain_geometry_and_preserve_feather() -> None:
    """Shift should constrain while Alt changes algebra without changing geometry."""
    modifiers = {"shift": False, "alt": False}
    commits = []
    tool = RectangleSelectionTool()
    tool.activate(
        PixelSelectionInteractionPort(
            panel_to_scene_point=lambda point: point,
            is_shift_held=lambda: modifiers["shift"],
            is_alt_held=lambda: modifiers["alt"],
            get_shape_feather_radius=lambda: 7.5,
            commit_coverage_item=lambda item: commits.append(item) or True,
        )
    )
    tool.mousePressEvent(
        _event(
            QEvent.Type.MouseButtonPress,
            QPointF(20.0, 20.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
    )
    modifiers.update(shift=True, alt=True)
    tool.mouseReleaseEvent(
        _event(
            QEvent.Type.MouseButtonRelease,
            QPointF(30.0, 25.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )
    )

    assert len(commits) == 1
    item = commits[0]
    assert item.geometry.local_bounds == (20.0, 20.0, 10.0, 10.0)
    assert item.feather_radius == 7.5
    assert item.combine_mode is CoverageCombineMode.REPLACE


def test_first_shape_gesture_uses_pointer_alt_without_centering_geometry() -> None:
    """A missed key press must not make the first Alt gesture additive or centered."""

    commits = []
    tool = RectangleSelectionTool()
    tool.activate(
        PixelSelectionInteractionPort(
            panel_to_scene_point=lambda point: point,
            is_alt_held=lambda: False,
            default_combine_mode=CoverageCombineMode.ADD,
            commit_coverage_item=lambda item: commits.append(item) or True,
        )
    )

    tool.mousePressEvent(
        _event(
            QEvent.Type.MouseButtonPress,
            QPointF(20.0, 20.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.AltModifier,
        )
    )
    tool.mouseReleaseEvent(
        _event(
            QEvent.Type.MouseButtonRelease,
            QPointF(30.0, 25.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.AltModifier,
        )
    )

    assert len(commits) == 1
    item = commits[0]
    assert item.combine_mode is CoverageCombineMode.SUBTRACT
    assert item.geometry.local_bounds == (20.0, 20.0, 10.0, 5.0)
