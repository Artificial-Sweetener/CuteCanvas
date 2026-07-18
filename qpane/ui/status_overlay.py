#    QPane - High-performance PySide6 image viewer
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

"""Render live QPane diagnostics in a lightweight stacked HUD overlay."""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPixmap
from PySide6.QtWidgets import QLabel, QWidget

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from ..qpane import QPane
logger = logging.getLogger(__name__)

STALE_CHECK_INTERVAL_MS = 250
STALE_THRESHOLD_SEC = 1.5
OVERLAY_MARGIN_PX = 12
OVERLAY_STYLESHEET = """
color: white;
padding: 4px 12px;
font-size: 12px;
font-family: "Consolas", "Courier New", monospace;
"""
FALLBACK_MESSAGE = "Diagnostics unavailable"
DROP_SHADOW_OFFSET = (0, 1)
DROP_SHADOW_COLOR = QColor(0, 0, 0, 230)
STROKE_COLOR = QColor(0, 0, 0)
STROKE_OFFSETS = (
    (-1, 0),
    (1, 0),
    (0, -1),
    (0, 1),
    (-1, -1),
    (-1, 1),
    (1, -1),
    (1, 1),
)
PADDING_VERTICAL_PX = 4
PADDING_HORIZONTAL_PX = 12


class QPaneStatusOverlay(QLabel):
    """Display live QPane diagnostics inside a translucent HUD anchored to the qpane."""

    def __init__(
        self,
        *,
        qpane: QPane,
        parent: QWidget | None = None,
    ) -> None:
        """Bind the overlay to `qpane`, connect diagnostics signals, and prep timers."""
        super().__init__(parent or qpane)
        self._qpane = qpane
        self._diagnostics = qpane.diagnostics()
        self._last_rendered_text = ""
        self._cached_pixmap: QPixmap | None = None
        self._pixmap_display_size = QSize()
        self._display_size = QSize()
        self._pending_show = False
        self._last_snapshot_rows: tuple[tuple[str, str], ...] = ()
        self._last_snapshot_monotonic = 0.0
        self._stale = False
        self._listening = False
        self._event_filter_installed = False
        self._scroll_offset = 0
        self._visible_size = QSize()
        self._stale_timer = QTimer(self)
        self._stale_timer.setInterval(STALE_CHECK_INTERVAL_MS)
        self._stale_timer.timeout.connect(self._check_stale)
        self._install_event_filter()
        self._apply_theme()
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.hide()

    def set_active(self, active: bool) -> None:
        """Show or hide the overlay while coordinating diagnostics updates.

        Args:
            active: Attach listeners, refresh immediately, and show the widget when True.
        """
        diagnostics = self._diagnostics
        if active:
            if not self._listening:
                self._connect_diagnostics()
            self._pending_show = True
            self._stale_timer.start()
            try:
                diagnostics.cached_snapshot(force=True)
            except Exception:  # pragma: no cover - defensive guard
                logger.exception("Failed to prime diagnostics overlay snapshot")
                fallback_rows = (("", FALLBACK_MESSAGE),)
                self._last_snapshot_rows = fallback_rows
                self._render_rows(fallback_rows, stale=False, force=True)
        else:
            self._stale_timer.stop()
            self._disconnect_diagnostics()
            self._pending_show = False
            self.hide()

    def refresh(self) -> None:
        """Force a diagnostics refresh without toggling visibility."""
        try:
            self._diagnostics.cached_snapshot(force=True)
        except Exception:  # pragma: no cover - defensive guard
            logger.exception("Failed to refresh diagnostics overlay snapshot")

    def _install_event_filter(self) -> None:
        """Attach to qpane resize events once so repositioning stays in sync."""
        if not self._event_filter_installed:
            self._qpane.installEventFilter(self)
            self._event_filter_installed = True

    def _apply_theme(self) -> None:
        """Apply the translucent HUD stylesheet to match the in-app diagnostics theme."""
        self.setStyleSheet(OVERLAY_STYLESHEET)

    def _connect_diagnostics(self) -> None:
        """Subscribe to diagnostics updates if not already listening."""
        if self._listening:
            return
        try:
            self._diagnostics.diagnosticsUpdated.connect(self._handle_snapshot)
        except Exception:  # pragma: no cover - defensive guard
            logger.exception("Failed to connect diagnostics overlay listener")
            return
        self._listening = True

    def _disconnect_diagnostics(self) -> None:
        """Detach diagnostics listeners."""
        if not self._listening:
            return
        try:
            self._diagnostics.diagnosticsUpdated.disconnect(self._handle_snapshot)
        except Exception:  # pragma: no cover - defensive guard
            logger.exception("Failed to disconnect diagnostics overlay listener")
        self._listening = False

    def _handle_snapshot(self, snapshot) -> None:
        """Render the provided diagnostics snapshot."""
        rows = snapshot.rows() if snapshot is not None else ()
        if rows:
            display_rows = rows
        elif self._last_snapshot_rows:
            display_rows = self._last_snapshot_rows
        else:
            display_rows = (("", FALLBACK_MESSAGE),)
        self._last_snapshot_rows = display_rows
        self._last_snapshot_monotonic = time.monotonic()
        self._update_stale_state(False)
        self._render_rows(display_rows, stale=False)

    def _render_rows(
        self, rows: Sequence[tuple[str, str]], *, stale: bool, force: bool = False
    ) -> None:
        """Render rows onto the pixmap and update positioning/visibility."""
        parent = self.parentWidget()
        width_limit: int | None = None
        available_height: int | None = None
        if parent is not None:
            width_limit = max(parent.width() - (OVERLAY_MARGIN_PX * 2), 1)
            available_height = max(parent.height() - (OVERLAY_MARGIN_PX * 2), 1)
        text = self._format_rows(rows, stale=stale, width_limit=width_limit)
        content_size = self._measure_content(text, self.font(), width_limit=width_limit)
        display_width = content_size.width() + (PADDING_HORIZONTAL_PX * 2)
        display_height = content_size.height() + (PADDING_VERTICAL_PX * 2)
        display_size = QSize(display_width, display_height)
        if not force and text == self._last_rendered_text:
            return
        self._last_rendered_text = text
        self._update_pixmap(
            text,
            display_size=display_size,
            content_size=content_size,
        )
        visible_height = display_size.height()
        if available_height is not None:
            visible_height = min(visible_height, available_height)
        self._display_size = display_size
        self._visible_size = QSize(display_size.width(), visible_height)
        # Show the most recent rows by default when anchored at the bottom-left.
        max_scroll = max(display_size.height() - visible_height, 0)
        self._scroll_offset = max_scroll
        self.setFixedSize(self._visible_size)
        self._reposition()
        if self._pending_show and text:
            self.show()
            self._pending_show = False

    def _format_rows(
        self,
        rows: Sequence[tuple[str, str]],
        *,
        stale: bool = False,
        width_limit: int | None = None,
    ) -> str:
        """Render normalized diagnostics rows into left-aligned text."""
        if not rows:
            return ""
        normalized = self._normalize_grouped_rows(rows)
        if not normalized:
            return ""
        metrics = self.fontMetrics()
        label_width = max(
            (len(label) for label, _ in normalized if label),
            default=0,
        )
        lines: list[str] = []
        for index, (label, value) in enumerate(normalized):
            has_label = bool(label)
            segments = value.splitlines() or [""]
            for seg_index, segment in enumerate(segments):
                display_label = label if seg_index == 0 else ""
                display_value = segment
                if stale and index == 0 and seg_index == 0:
                    display_value = f"{display_value} (stale)"
                if label_width and display_label:
                    base_line = f"{display_label.ljust(label_width)}  {display_value}"
                elif label_width and not display_label and has_label:
                    indent = " " * label_width
                    base_line = f"{indent}  {display_value}"
                else:
                    base_line = display_value
                lines.extend(
                    self._wrap_text(
                        base_line.rstrip(), metrics, width_limit=width_limit
                    )
                )
        return "\n".join(lines)

    def _wrap_text(
        self,
        text: str,
        metrics,
        *,
        width_limit: int | None = None,
    ) -> list[str]:
        """Wrap text to the provided pixel width using whitespace-aware breaks."""
        if not text or width_limit is None:
            return [text]

        def _line_fits(candidate: str) -> bool:
            """Return True when ``candidate`` fits within the width budget."""
            return metrics.horizontalAdvance(candidate) <= width_limit

        words = text.split(" ")
        lines: list[str] = []
        current = ""

        def _break_token(token: str) -> list[str]:
            """Split an oversized token into pieces that fit the width limit."""
            pieces: list[str] = []
            start = 0
            length = len(token)
            while start < length:
                end = start + 1
                while (
                    end <= length
                    and metrics.horizontalAdvance(token[start:end]) <= width_limit
                ):
                    end += 1
                if end == start + 1:
                    # Fallback to single character progression.
                    pieces.append(token[start:end])
                    start = end
                    continue
                end -= 1
                pieces.append(token[start:end])
                start = end
            return pieces

        for word in words:
            next_segments = _break_token(word) if not _line_fits(word) else [word]
            for segment in next_segments:
                if not current:
                    current = segment
                    continue
                candidate = f"{current} {segment}"
                if _line_fits(candidate):
                    current = candidate
                else:
                    lines.append(current)
                    current = segment
        if current:
            lines.append(current)
        return lines

    def _measure_content(
        self, text: str, font, *, width_limit: int | None = None
    ) -> QSize:
        """Return the content size for ``text`` using ``font``."""
        metrics = QFontMetrics(font)
        if width_limit is not None:
            bounding_rect = metrics.boundingRect(
                QRect(0, 0, width_limit, 10_000),
                Qt.TextWordWrap,
                text,
            )
        else:
            bounding_rect = metrics.boundingRect(text or "")
        width = bounding_rect.width()
        stroke_left = max(
            (-offset_dx for offset_dx, _ in STROKE_OFFSETS if offset_dx < 0), default=0
        )
        stroke_right = max(
            (offset_dx for offset_dx, _ in STROKE_OFFSETS if offset_dx > 0), default=0
        )
        stroke_up = max(
            (-offset_dy for _, offset_dy in STROKE_OFFSETS if offset_dy < 0), default=0
        )
        stroke_down = max(
            (offset_dy for _, offset_dy in STROKE_OFFSETS if offset_dy > 0), default=0
        )
        shadow_x = max(DROP_SHADOW_OFFSET[0], 0) if DROP_SHADOW_OFFSET else 0
        shadow_y = max(DROP_SHADOW_OFFSET[1], 0) if DROP_SHADOW_OFFSET else 0
        height = bounding_rect.height() + stroke_up + stroke_down + shadow_y
        extra_x = stroke_left + stroke_right + shadow_x
        width += extra_x
        return QSize(width, height)

    def _normalize_grouped_rows(
        self, rows: Sequence[tuple[str, str]]
    ) -> list[tuple[str, str]]:
        """Expand grouped diagnostics labels into display-friendly rows."""
        final_rows: list[tuple[str, str]] = []
        for label, value in rows:
            if "|" not in label:
                final_rows.append((label, value))
                continue
            group, key = label.split("|", 1)
            group = group.strip()
            key = key.strip()
            display_label = f"{group} | {key}" if key else group
            final_rows.append((display_label, value))
        return final_rows

    def _update_pixmap(
        self,
        text: str,
        *,
        display_size: QSize,
        content_size: QSize,
    ) -> None:
        """Render the overlay text into a cached pixmap."""
        if not text:
            self._cached_pixmap = None
            self.update()
            return
        dpr = self.devicePixelRatioF() if hasattr(self, "devicePixelRatioF") else 1.0
        total_width_px = max(1, int(display_size.width() * dpr))
        total_height_px = max(1, int(display_size.height() * dpr))
        pixmap = QPixmap(total_width_px, total_height_px)
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setFont(self.font())
        text_rect = QRect(
            PADDING_HORIZONTAL_PX,
            PADDING_VERTICAL_PX,
            content_size.width(),
            content_size.height(),
        )
        painter.setPen(STROKE_COLOR)
        for offset_dx, offset_dy in STROKE_OFFSETS:
            painter.drawText(
                text_rect.translated(offset_dx, offset_dy),
                Qt.AlignLeft | Qt.AlignTop,
                text,
            )
        shadow_dx, shadow_dy = DROP_SHADOW_OFFSET
        painter.setPen(DROP_SHADOW_COLOR)
        if shadow_dx or shadow_dy:
            painter.drawText(
                text_rect.translated(shadow_dx, shadow_dy),
                Qt.AlignLeft | Qt.AlignTop,
                text,
            )
        else:
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignTop, text)
        painter.setPen(Qt.white)
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignTop, text)
        painter.end()
        self._cached_pixmap = pixmap
        self._pixmap_display_size = display_size
        self.update()

    def _reposition(self) -> None:
        """Anchor the overlay near the qpane's bottom-left corner."""
        parent = self.parentWidget()
        if parent is None or self._cached_pixmap is None:
            return
        visible = getattr(self, "_visible_size", None) or self._pixmap_display_size
        display_width = visible.width() or self._cached_pixmap.width()
        display_height = visible.height() or self._cached_pixmap.height()
        margin = OVERLAY_MARGIN_PX
        label_width = display_width
        target_height = display_height
        target_x = margin
        if parent.width() < label_width + margin:
            target_x = max(parent.width() - label_width, 0)
        target_y = parent.height() - target_height - margin
        if target_y < margin:
            target_y = max(parent.height() - target_height, 0)
        target_rect = QRect(target_x, target_y, label_width, target_height)
        if self.geometry() == target_rect:
            return
        self.setGeometry(target_rect)

    def _check_stale(self) -> None:
        """Mark the overlay stale when the last snapshot exceeds the timeout."""
        if not self._last_snapshot_rows:
            return
        elapsed = time.monotonic() - self._last_snapshot_monotonic
        is_stale = elapsed >= STALE_THRESHOLD_SEC
        self._update_stale_state(is_stale)

    def _update_stale_state(self, stale: bool) -> None:
        """Update cached stale flag and force a re-render when it changes."""
        if self._stale == stale:
            return
        self._stale = stale
        self._render_rows(self._last_snapshot_rows, stale=stale, force=True)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Reposition the overlay when the qpane resizes."""
        if watched is self._qpane and event.type() == QEvent.Resize:
            if self._last_snapshot_rows:
                self._render_rows(
                    self._last_snapshot_rows, stale=self._stale, force=True
                )
            else:
                self._reposition()
        return super().eventFilter(watched, event)

    def paintEvent(self, event: QEvent) -> None:
        """Draw the cached pixmap for the current diagnostics text."""
        if self._cached_pixmap is None:
            super().paintEvent(event)
            return
        painter = QPainter(self)
        offset = getattr(self, "_scroll_offset", 0)
        logical_size = self._pixmap_display_size
        target_rect = QRect(0, -offset, logical_size.width(), logical_size.height())
        painter.drawPixmap(target_rect, self._cached_pixmap, self._cached_pixmap.rect())

    def closeEvent(self, event: QEvent) -> None:
        """Tear down timers and event filters before closing."""
        self._stale_timer.stop()
        if self._event_filter_installed:
            try:
                self._qpane.removeEventFilter(self)
            except Exception:  # pragma: no cover - defensive guard
                logger.exception("Failed to detach status overlay event filter")
            self._event_filter_installed = False
        super().closeEvent(event)

    def wheelEvent(self, event):  # type: ignore[override]
        """Allow vertical scrolling when content exceeds the visible area."""
        if self._cached_pixmap is None:
            return super().wheelEvent(event)
        visible_height = getattr(self, "_visible_size", QSize()).height() or 0
        content_height = (
            self._pixmap_display_size.height() or self._cached_pixmap.height()
        )
        max_scroll = max(content_height - visible_height, 0)
        if max_scroll <= 0:
            return super().wheelEvent(event)
        delta = event.angleDelta().y()
        if not delta:
            return super().wheelEvent(event)
        step = 30  # pixels per wheel notch
        new_offset = self._scroll_offset - int(delta / 120 * step)
        self._scroll_offset = max(0, min(max_scroll, new_offset))
        self.update()
        event.accept()
