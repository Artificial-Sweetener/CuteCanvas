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

"""Tests for the editor's authoritative overlay state owner."""

from __future__ import annotations

from cutecanvas.tools.overlay_controller import EditorOverlayController


def test_overlay_controller_starts_visible() -> None:
    """A fresh editor overlay owner has no pending navigation handoff."""
    controller = EditorOverlayController(lambda: None)
    assert controller.suspended is False
    assert controller.resume_pending is False


def test_overlay_controller_suspends_and_resumes_atomically() -> None:
    """Navigation state changes never leave only one suspension flag set."""
    controller = EditorOverlayController(lambda: None)
    controller.suspend()
    assert controller.suspended is True
    assert controller.resume_pending is True
    controller.resume()
    assert controller.suspended is False
    assert controller.resume_pending is False


def test_overlay_controller_repaint_is_explicit() -> None:
    """Only repainting resume requests schedule a new widget frame."""
    repaints: list[bool] = []
    controller = EditorOverlayController(lambda: repaints.append(True))
    controller.suspend()
    controller.resume()
    assert not repaints
    controller.suspend()
    controller.resume(repaint=True)
    assert repaints == [True]


def test_overlay_controller_uses_shared_qpane_registry() -> None:
    """Content overlay registration remains a single shared implementation."""
    controller = EditorOverlayController(lambda: None)
    draw = lambda _painter, _state: None
    controller.register_content("test", draw)
    assert controller.content == {"test": draw}
    controller.unregister_content("test")
    assert not controller.content
