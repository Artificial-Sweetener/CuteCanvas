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
"""Clone Stamp source gesture and shared brush-lifecycle contracts."""

from __future__ import annotations

from cutecanvas.painting import BrushStrokeSegment
from cutecanvas.painting.tools import CloneStampTool
from cutecanvas.painting.tools.brush_preview import AffineBrushPreview
from cutecanvas.tools.ports import (
    CloneStampInteractionPort,
    PaintingInteractionPort,
)
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from qpane import PointerDeviceKind, PointerPhase, PointerSample


class _MouseEventStub:
    """Provide the mouse values used by brush tools without a window system."""

    def __init__(
        self,
        point: QPointF,
        *,
        modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier,
    ) -> None:
        """Capture one left-button event position."""
        self._point = QPointF(point)
        self._modifiers = modifiers
        self.accepted = False

    def button(self) -> Qt.MouseButton:
        """Return the primary button."""
        return Qt.MouseButton.LeftButton

    def position(self) -> QPointF:
        """Return the detached logical event position."""
        return QPointF(self._point)

    def modifiers(self) -> Qt.KeyboardModifier:
        """Return the modifiers captured with this event."""
        return self._modifiers

    def accept(self) -> None:
        """Record event acceptance."""
        self.accepted = True


def _port(
    *,
    alt_held,
    set_source=lambda _point: False,
    source_set=lambda: False,
    source_position=lambda: None,
    brush_size: int = 9,
    zoom: float = 1.0,
    dpr: float = 1.0,
    pressure_diameter=None,
    footprint_diameters: list[float] | None = None,
) -> CloneStampInteractionPort:
    """Return a clone port with identity panel/target coordinates."""

    def footprint(diameter: float) -> AffineBrushPreview | None:
        """Project a circular test footprint through scalar view geometry."""
        if footprint_diameters is not None:
            footprint_diameters.append(diameter)
        center = source_position()
        if center is None:
            return None
        radius = diameter * zoom / dpr / 2.0
        return AffineBrushPreview(
            center.x(),
            center.y(),
            radius,
            0.0,
            0.0,
            radius,
        )

    return CloneStampInteractionPort(
        painting=PaintingInteractionPort(
            is_alt_held=alt_held,
            get_brush_size=lambda: brush_size,
            panel_to_target_point=lambda point: QPointF(point),
            get_zoom=lambda: zoom,
            get_dpr=lambda: dpr,
            get_pressure_diameter=pressure_diameter,
        ),
        set_source_from_panel=set_source,
        source_footprint=footprint,
        source_set=source_set,
    )


def test_clone_stamp_modifier_click_sets_source_without_starting_stroke(qapp) -> None:
    """A modified click configures the source and emits no history or paint work."""
    tool = CloneStampTool()
    sources: list[QPointF] = []
    strokes: list[BrushStrokeSegment] = []
    undo_requests: list[None] = []
    cursor_requests: list[None] = []
    tool.signals.stroke_applied.connect(strokes.append)
    tool.signals.undo_state_push_requested.connect(lambda: undo_requests.append(None))
    tool.signals.cursor_update_requested.connect(lambda: cursor_requests.append(None))
    tool.activate(
        _port(
            alt_held=lambda: False,
            set_source=lambda point: not sources.append(QPointF(point)),
        )
    )
    event = _MouseEventStub(
        QPointF(12.5, 8.25),
        modifiers=Qt.KeyboardModifier.AltModifier,
    )

    tool.mousePressEvent(event)

    assert event.accepted
    assert sources == [QPointF(12.5, 8.25)]
    assert strokes == []
    assert undo_requests == []
    assert cursor_requests == [None]


def test_clone_stamp_modifier_pen_contact_sets_source_without_painting(qapp) -> None:
    """Direct pen input must use its event-local modifier for source capture."""
    tool = CloneStampTool()
    sources: list[QPointF] = []
    strokes: list[BrushStrokeSegment] = []
    tool.signals.stroke_applied.connect(strokes.append)
    tool.activate(
        _port(
            alt_held=lambda: False,
            set_source=lambda point: not sources.append(QPointF(point)),
        )
    )
    sample = PointerSample(
        pointer_id=9,
        device=PointerDeviceKind.PEN,
        phase=PointerPhase.BEGIN,
        position=QPointF(18.25, 27.5),
        global_position=QPointF(18.25, 27.5),
        pressure=0.65,
        buttons=Qt.MouseButton.LeftButton,
        modifiers=Qt.KeyboardModifier.AltModifier,
        timestamp_ms=1,
    )

    assert tool.handle_pointer_sample(sample)
    assert sources == [QPointF(18.25, 27.5)]
    assert strokes == []
    assert not tool.is_drawing


def test_clone_stamp_source_footprint_tracks_pressure_adjusted_diameter(qapp) -> None:
    """Sample feedback must consume the shared brush's live pressure diameter."""
    tool = CloneStampTool()
    footprint_diameters: list[float] = []
    tool.activate(
        _port(
            alt_held=lambda: False,
            source_set=lambda: True,
            source_position=lambda: QPointF(40.0, 40.0),
            brush_size=20,
            pressure_diameter=lambda pressure: 20.0 * pressure,
            footprint_diameters=footprint_diameters,
        )
    )
    sample = PointerSample(
        pointer_id=10,
        device=PointerDeviceKind.PEN,
        phase=PointerPhase.BEGIN,
        position=QPointF(18.0, 27.0),
        global_position=QPointF(18.0, 27.0),
        pressure=0.5,
        buttons=Qt.MouseButton.LeftButton,
        modifiers=Qt.KeyboardModifier.NoModifier,
        timestamp_ms=1,
    )

    assert tool.handle_pointer_sample(sample)
    assert tool.pointer_preview is not None
    assert tool.pointer_preview.diameter == 10.0
    assert footprint_diameters[-1] == 10.0


def test_clone_stamp_uses_shared_brush_stroke_and_temporary_suspend(qapp) -> None:
    """Clone painting commits through the shared stroke boundary before navigation."""
    tool = CloneStampTool()
    strokes: list[BrushStrokeSegment] = []
    completed: list[None] = []
    cancelled: list[None] = []
    tool.signals.stroke_applied.connect(strokes.append)
    tool.signals.stroke_completed.connect(lambda: completed.append(None))
    tool.signals.stroke_cancelled.connect(lambda: cancelled.append(None))
    tool.activate(_port(alt_held=lambda: False, source_set=lambda: True))
    event = _MouseEventStub(QPointF(7.0, 11.0))

    tool.mousePressEvent(event)
    suspended = tool.suspend_for_temporary_navigation()

    assert event.accepted
    assert suspended
    assert len(strokes) == 1
    assert strokes[0].start == strokes[0].end == (7.0, 11.0)
    assert not strokes[0].erase
    assert completed == [None]
    assert cancelled == []
    assert not tool.is_drawing


def test_clone_stamp_without_source_uses_unavailable_cursor(qapp) -> None:
    """The tool advertises unavailable painting until a source exists."""
    tool = CloneStampTool()
    tool.activate(_port(alt_held=lambda: False))

    cursor = tool.getCursor()

    assert cursor is not None
    assert cursor.shape() is Qt.CursorShape.ForbiddenCursor


def test_clone_stamp_source_feedback_matches_scaled_brush_footprint(qapp) -> None:
    """Source feedback must show the sampled diameter instead of a fixed marker."""
    tool = CloneStampTool()
    tool.activate(
        _port(
            alt_held=lambda: False,
            source_set=lambda: True,
            source_position=lambda: QPointF(50.0, 50.0),
            brush_size=20,
            zoom=2.0,
        )
    )
    image = QImage(100, 100, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)

    tool.draw_overlay(painter)
    painter.end()

    painted = [
        (x, y)
        for y in range(image.height())
        for x in range(image.width())
        if QColor(image.pixelColor(x, y)).alpha() > 0
    ]
    assert painted
    xs = [point[0] for point in painted]
    ys = [point[1] for point in painted]
    assert 43 <= max(xs) - min(xs) + 1 <= 47
    assert 43 <= max(ys) - min(ys) + 1 <= 47
    assert image.pixelColor(50, 50).alpha() > 0
