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

"""Probe QScreen.refreshRateChanged to confirm refresh updates at runtime."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QLabel, QWidget


def _format_rate(value: float | None) -> str:
    """Return a readable refresh rate label."""
    if value is None:
        return "unknown"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "unknown"
    if numeric <= 0:
        return "unknown"
    return f"{numeric:.2f} Hz"


def _apply_refresh(label: QLabel, rate: float | None) -> None:
    """Update the label with the detected refresh rate."""
    label.setText(f"Refresh rate: {_format_rate(rate)}")


def main() -> int:
    """Run the Qt app and log refresh-rate change notifications."""
    app = QApplication(sys.argv)
    window = QWidget()
    window.setWindowTitle("Refresh Rate Probe")
    label = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
    label.setMinimumSize(320, 120)
    layout = QGuiApplication.primaryScreen()
    if layout is None:
        _apply_refresh(label, None)
    else:
        _apply_refresh(label, layout.refreshRate())
    screen = window.screen()
    if screen is None:
        _apply_refresh(label, None)
    else:
        _apply_refresh(label, screen.refreshRate())
        screen.refreshRateChanged.connect(lambda rate: _apply_refresh(label, rate))
        screen.refreshRateChanged.connect(
            lambda rate: print(f"Refresh rate changed: {_format_rate(rate)}")
        )
    window_layout = None
    try:
        from PySide6.QtWidgets import QVBoxLayout

        window_layout = QVBoxLayout(window)
        window_layout.addWidget(label)
    except (RuntimeError, TypeError):
        label.setParent(window)
        label.move(20, 40)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
