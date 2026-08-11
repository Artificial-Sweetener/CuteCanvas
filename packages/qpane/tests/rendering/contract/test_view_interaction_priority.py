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
"""Contract proof for rendering priority requested by advanced hosts."""

from __future__ import annotations

from qpane.sdk.rendering import View


class _Presenter:
    """Record the derived-rendering lifecycle around one priority pulse."""

    def __init__(self, events: list[str]) -> None:
        """Retain the shared ordered event sink."""
        self._events = events

    def begin_navigation_interaction(self) -> None:
        """Record refinement suspension."""
        self._events.append("suspend")

    def finish_navigation_interaction(self) -> None:
        """Record settled-refinement scheduling."""
        self._events.append("settle")


class _Renderer:
    """Record cancellation of an incomplete exact frame."""

    def __init__(self, events: list[str]) -> None:
        """Retain the shared ordered event sink."""
        self._events = events

    def cancel_navigation_refinement(self) -> None:
        """Record exact-frame cancellation."""
        self._events.append("cancel-exact")


def test_host_interaction_preempts_derived_rendering_before_settlement() -> None:
    """A priority pulse must suspend, cancel, and then schedule settlement."""
    events: list[str] = []
    view = View.__new__(View)
    object.__setattr__(view, "presenter", _Presenter(events))
    object.__setattr__(view, "renderer", _Renderer(events))

    view.prioritize_interaction()

    assert events == ["suspend", "cancel-exact", "settle"]
