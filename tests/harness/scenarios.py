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

"""Deterministic and seeded action builders for CuteCanvas abuse sessions."""

from __future__ import annotations

import random

from .abuse_model import (
    AbuseAction,
    EditorWorkflowAction,
    HarnessPoint,
    IdleAction,
    MouseHoverAction,
    PalmContactAction,
    PenHoverAction,
    PenLeaveAction,
    PointerKind,
    RedoAction,
    StrokeAction,
    TouchNavigationAction,
    UndoAction,
    WaitAction,
)


def deterministic_abuse_actions() -> tuple[AbuseAction, ...]:
    """Return a compact cross-device intersection and history scenario."""
    return (
        EditorWorkflowAction(),
        StrokeAction(
            PointerKind.MOUSE,
            _points((70, 120), (430, 120)),
            mask_index=0,
            brush_size=120,
        ),
        StrokeAction(
            PointerKind.TOUCH,
            _points(
                (250, 60),
                (250, 90),
                (250, 120),
                (250, 150),
                (250, 180),
                (250, 220),
                (250, 260),
                (250, 300),
                (250, 340),
                (250, 390),
                (250, 440),
            ),
            mask_index=1,
            brush_size=120,
            step_delay_ms=2,
        ),
        StrokeAction(
            PointerKind.PEN,
            _points((90, 400), (200, 300), (310, 200), (420, 90)),
            mask_index=0,
            brush_size=180,
            pressure=0.7,
        ),
        PalmContactAction(point=HarnessPoint(450, 450), mask_index=0),
        PenLeaveAction(),
        WaitAction(wait_ms=850),
        PenHoverAction(
            point=HarnessPoint(420, 420),
            mask_index=0,
            brush_size=140,
        ),
        PenLeaveAction(),
        WaitAction(wait_ms=850),
        UndoAction(mask_index=1),
        RedoAction(mask_index=1),
        StrokeAction(
            PointerKind.TOUCH,
            _points((80, 360), (180, 280), (280, 200), (380, 120)),
            mask_index=1,
            brush_size=128,
        ),
        StrokeAction(
            PointerKind.MOUSE,
            _points(
                (140, 210),
                (360, 210),
                (360, 350),
                (140, 350),
                (140, 210),
                (360, 350),
            ),
            mask_index=0,
            brush_size=112,
            step_delay_ms=1,
        ),
        IdleAction(wait_ms=15),
        UndoAction(mask_index=0),
        StrokeAction(
            PointerKind.TOUCH,
            _points((100, 330), (180, 350), (260, 330), (340, 350), (420, 330)),
            mask_index=0,
            brush_size=104,
        ),
        IdleAction(wait_ms=15),
        TouchNavigationAction(
            primary_start=HarnessPoint(80, 70),
            secondary_start=HarnessPoint(180, 70),
            primary_end=HarnessPoint(60, 120),
            secondary_end=HarnessPoint(260, 180),
            mask_index=1,
        ),
        MouseHoverAction(
            point=HarnessPoint(300, 300),
            stale_touchscreen_metadata=True,
        ),
        IdleAction(wait_ms=15),
    )


def ordered_device_history_actions(
    first: PointerKind,
    second: PointerKind,
) -> tuple[AbuseAction, ...]:
    """Exercise one ordered device transition through full history branching."""
    actions: list[AbuseAction] = [
        StrokeAction(
            first,
            _points((70, 130), (180, 180), (300, 130), (430, 180)),
            brush_size=96,
            step_delay_ms=0,
        )
    ]
    _append_pen_exit(actions, first, second)
    if second is PointerKind.MOUSE:
        mouse_position = (
            HarnessPoint(430, 180)
            if first is PointerKind.TOUCH
            else HarnessPoint(220, 220)
        )
        actions.append(
            MouseHoverAction(
                point=mouse_position,
                stale_touchscreen_metadata=first is PointerKind.TOUCH,
            )
        )
    actions.append(
        StrokeAction(
            second,
            _points((250, 60), (250, 150), (250, 250), (250, 350), (250, 440)),
            brush_size=112,
            step_delay_ms=3,
            pressure=0.6,
        )
    )
    _append_pen_exit(actions, second, None)
    actions.extend(
        (
            UndoAction(),
            UndoAction(),
            RedoAction(),
            RedoAction(),
            UndoAction(),
        )
    )
    if second is PointerKind.PEN and first is PointerKind.TOUCH:
        actions.append(WaitAction(wait_ms=850))
    if first is PointerKind.MOUSE:
        mouse_position = (
            HarnessPoint(250, 440)
            if second is PointerKind.TOUCH
            else HarnessPoint(300, 280)
        )
        actions.append(
            MouseHoverAction(
                point=mouse_position,
                stale_touchscreen_metadata=second is PointerKind.TOUCH,
            )
        )
    actions.append(
        StrokeAction(
            first,
            _points((80, 390), (170, 310), (260, 390), (350, 310), (430, 390)),
            brush_size=88,
            step_delay_ms=1,
            pressure=0.8,
        )
    )
    _append_pen_exit(actions, first, None)
    actions.append(IdleAction(wait_ms=20))
    return tuple(actions)


def repeated_touch_mouse_cursor_actions() -> tuple[AbuseAction, ...]:
    """Alternate touch and mouse repeatedly while exercising shared history."""
    actions: list[AbuseAction] = []
    touch_strokes = (
        _points((70, 100), (180, 140), (300, 100), (430, 140)),
        _points((90, 220), (190, 180), (310, 220), (410, 180)),
        _points((70, 300), (180, 350), (300, 300), (430, 350)),
        _points((100, 420), (190, 370), (310, 420), (400, 370)),
    )
    mouse_strokes = (
        _points((430, 140), (330, 200), (220, 260), (100, 320)),
        _points((410, 180), (320, 240), (220, 300), (90, 360)),
        _points((430, 350), (330, 290), (220, 230), (70, 170)),
        _points((400, 370), (310, 310), (200, 250), (100, 190)),
    )
    for index, (touch_points, mouse_points) in enumerate(
        zip(touch_strokes, mouse_strokes, strict=True)
    ):
        actions.append(
            StrokeAction(
                PointerKind.TOUCH,
                touch_points,
                brush_size=84 + index * 8,
                step_delay_ms=3 if index % 2 else 0,
            )
        )
        actions.append(
            MouseHoverAction(
                point=touch_points[-1],
                stale_touchscreen_metadata=True,
            )
        )
        actions.append(
            StrokeAction(
                PointerKind.MOUSE,
                mouse_points,
                brush_size=92 + index * 6,
                step_delay_ms=index % 2,
            )
        )
    actions.extend((UndoAction(), UndoAction(), UndoAction(), UndoAction()))
    actions.extend((RedoAction(), RedoAction()))
    branch_points = _points((80, 250), (170, 250), (260, 250), (350, 250), (430, 250))
    actions.append(
        StrokeAction(
            PointerKind.TOUCH,
            branch_points,
            brush_size=118,
            step_delay_ms=2,
        )
    )
    actions.append(
        MouseHoverAction(
            point=branch_points[-1],
            stale_touchscreen_metadata=True,
        )
    )
    actions.append(
        StrokeAction(
            PointerKind.MOUSE,
            _points((430, 250), (340, 250), (250, 250), (160, 250), (70, 250)),
            brush_size=72,
        )
    )
    actions.append(IdleAction(wait_ms=25))
    return tuple(actions)


def touch_mouse_mask_switch_actions() -> tuple[AbuseAction, ...]:
    """Alternate touch and mouse while switching mask ownership."""
    first_touch = _points((70, 120), (180, 100), (300, 140), (430, 120))
    second_touch = _points((80, 340), (190, 380), (310, 330), (430, 360))
    return (
        StrokeAction(
            PointerKind.TOUCH,
            first_touch,
            mask_index=0,
            brush_size=110,
        ),
        MouseHoverAction(
            point=first_touch[-1],
            stale_touchscreen_metadata=True,
        ),
        StrokeAction(
            PointerKind.MOUSE,
            _points((430, 120), (340, 190), (250, 250), (160, 310), (70, 380)),
            mask_index=1,
            brush_size=96,
        ),
        StrokeAction(
            PointerKind.TOUCH,
            second_touch,
            mask_index=1,
            brush_size=124,
            step_delay_ms=3,
        ),
        MouseHoverAction(
            point=second_touch[-1],
            stale_touchscreen_metadata=True,
        ),
        StrokeAction(
            PointerKind.MOUSE,
            _points((430, 360), (340, 300), (250, 250), (160, 200), (70, 140)),
            mask_index=0,
            brush_size=82,
        ),
        UndoAction(mask_index=0),
        UndoAction(mask_index=1),
        RedoAction(mask_index=0),
        RedoAction(mask_index=1),
        IdleAction(wait_ms=25),
    )


def overlapping_noop_stroke_actions() -> tuple[AbuseAction, ...]:
    """Cover one path, then repaint wholly inside it with mouse and pen."""
    covered_path = _points((140, 140), (250, 250), (360, 360))
    return (
        StrokeAction(
            PointerKind.TOUCH,
            covered_path,
            brush_size=160,
            step_delay_ms=2,
        ),
        MouseHoverAction(
            point=covered_path[-1],
            stale_touchscreen_metadata=True,
        ),
        StrokeAction(
            PointerKind.MOUSE,
            tuple(reversed(covered_path)),
            brush_size=120,
            step_delay_ms=2,
        ),
        StrokeAction(
            PointerKind.PEN,
            _points((200, 200), (300, 300)),
            brush_size=100,
            pressure=0.5,
        ),
        PenLeaveAction(),
        IdleAction(wait_ms=25),
    )


def seeded_abuse_actions(seed: int, *, random_strokes: int) -> tuple[AbuseAction, ...]:
    """Extend the deterministic scenario with reproducible random abuse."""
    random_source = random.Random(seed)
    actions = list(deterministic_abuse_actions())
    history_depth = [2, 2]
    devices = tuple(PointerKind)
    for stroke_index in range(random_strokes):
        mask_index = stroke_index % 2
        if stroke_index > 0 and stroke_index % 5 == 0 and history_depth[mask_index]:
            actions.append(UndoAction(mask_index=mask_index))
            history_depth[mask_index] -= 1
        action = _random_stroke(
            random_source,
            device=devices[stroke_index % len(devices)],
            mask_index=mask_index,
            slow=stroke_index % 4 == 1,
        )
        actions.append(action)
        history_depth[mask_index] += 1
        if action.device is PointerKind.PEN:
            actions.extend((PenLeaveAction(), WaitAction(wait_ms=850)))
        if stroke_index % 3 == 2:
            actions.append(IdleAction(wait_ms=5))
    return tuple(actions)


def _random_stroke(
    random_source: random.Random,
    *,
    device: PointerKind,
    mask_index: int,
    slow: bool,
) -> StrokeAction:
    """Build one bounded random walk with intentionally uneven sampling."""
    point_count = random_source.randint(2, 9)
    x_position = random_source.randint(70, 430)
    y_position = random_source.randint(70, 430)
    points = [HarnessPoint(x_position, y_position)]
    for _ in range(point_count - 1):
        x_position = min(440, max(60, x_position + random_source.randint(-150, 150)))
        y_position = min(440, max(60, y_position + random_source.randint(-150, 150)))
        points.append(HarnessPoint(x_position, y_position))
    return StrokeAction(
        device=device,
        points=tuple(points),
        mask_index=mask_index,
        brush_size=random_source.randint(96, 180),
        step_delay_ms=random_source.randint(2, 5) if slow else 0,
        pressure=random_source.uniform(0.25, 1.0),
    )


def _append_pen_exit(
    actions: list[AbuseAction],
    previous: PointerKind,
    following: PointerKind | None,
) -> None:
    """End pen proximity and honor the touch-arbitration cooldown when needed."""
    if previous is not PointerKind.PEN:
        return
    actions.append(PenLeaveAction())
    if following is PointerKind.TOUCH:
        actions.append(WaitAction(wait_ms=850))


def _points(*coordinates: tuple[int, int]) -> tuple[HarnessPoint, ...]:
    """Create immutable serializable points from concise coordinate pairs."""
    return tuple(
        HarnessPoint(x_position, y_position) for x_position, y_position in coordinates
    )
