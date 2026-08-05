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
from cutecanvas.cursor import EditorCursorIntent
from cutecanvas.tools.ports import (
    PixelSelectionInteractionPort,
    SelectionTranslationPort,
)
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


def test_delete_routes_only_through_selection_tool_pixel_clear_port() -> None:
    """Delete should clear selected pixels only when this tool owns the key."""
    clear_requests: list[None] = []
    selection_tool = RectangleSelectionTool()
    selection_tool.activate(
        PixelSelectionInteractionPort(
            clear_selected_pixels=lambda: clear_requests.append(None) or True,
        )
    )
    delete = QKeyEvent(QEvent.Type.KeyPress, Qt.Key_Delete, Qt.NoModifier)

    selection_tool.keyPressEvent(delete)

    assert delete.isAccepted()
    assert clear_requests == [None]

    mask_shape_tool = RectangleSelectionTool()
    mask_shape_tool.activate(PixelSelectionInteractionPort())
    mask_delete = QKeyEvent(QEvent.Type.KeyPress, Qt.Key_Delete, Qt.NoModifier)

    mask_shape_tool.keyPressEvent(mask_delete)

    assert not mask_delete.isAccepted()


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


def test_inside_selection_drag_moves_only_selection_coverage() -> None:
    """An inside press should route through selection translation, not authoring."""
    calls: list[tuple[str, QPointF]] = []
    commits = []
    tool = RectangleSelectionTool()
    tool.activate(
        PixelSelectionInteractionPort(
            panel_to_scene_point=lambda point: point + QPointF(10.0, 20.0),
            commit_coverage_item=lambda item: commits.append(item) or True,
            translation=SelectionTranslationPort(
                begin=lambda point: calls.append(("begin", point)) or True,
                update=lambda point: calls.append(("update", point)) or True,
                finish=lambda point: calls.append(("finish", point)) or True,
            ),
        )
    )

    _drag(tool, [QPointF(2.0, 3.0), QPointF(7.0, 9.0)])

    assert calls == [
        ("begin", QPointF(12.0, 23.0)),
        ("finish", QPointF(17.0, 29.0)),
    ]
    assert not commits


def test_alt_inside_selection_remains_subtractive_authoring() -> None:
    """Alt should bypass boundary movement and author subtractive coverage."""
    move_begins: list[QPointF] = []
    commits = []
    tool = RectangleSelectionTool()
    tool.activate(
        PixelSelectionInteractionPort(
            panel_to_scene_point=lambda point: point,
            commit_coverage_item=lambda item: commits.append(item) or True,
            translation=SelectionTranslationPort(
                begin=lambda point: move_begins.append(point) or True,
            ),
        )
    )
    modifiers = Qt.KeyboardModifier.AltModifier

    tool.mousePressEvent(
        _event(
            QEvent.Type.MouseButtonPress,
            QPointF(2.0, 3.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            modifiers,
        )
    )
    tool.mouseReleaseEvent(
        _event(
            QEvent.Type.MouseButtonRelease,
            QPointF(7.0, 9.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            modifiers,
        )
    )

    assert not move_begins
    assert len(commits) == 1
    assert commits[0].combine_mode is CoverageCombineMode.SUBTRACT


def test_selection_tool_reports_semantic_cursor_intents() -> None:
    """Selection state should describe meaning without constructing QCursor artwork."""

    modifiers = {"alt": False, "shift": False}
    hovered = {"inside": False}
    tool = RectangleSelectionTool()
    tool.activate(
        PixelSelectionInteractionPort(
            panel_to_scene_point=lambda point: point,
            is_alt_held=lambda: modifiers["alt"],
            is_shift_held=lambda: modifiers["shift"],
            translation=SelectionTranslationPort(
                can_begin=lambda _point: hovered["inside"],
            ),
        )
    )

    assert tool.cursor_intent() is EditorCursorIntent.PRECISE
    modifiers["alt"] = True
    assert tool.cursor_intent() is EditorCursorIntent.PRECISE_SUBTRACT
    modifiers["alt"] = False
    modifiers["shift"] = True
    assert tool.cursor_intent() is EditorCursorIntent.PRECISE_ADD
    modifiers["shift"] = False
    hovered["inside"] = True
    tool.mouseMoveEvent(
        _event(
            QEvent.Type.MouseMove,
            QPointF(5.0, 5.0),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
        )
    )
    assert tool.cursor_intent() is EditorCursorIntent.SELECTION_TRANSLATE
