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

"""Prove bounded work can bridge QPane cancellation without polling."""

from __future__ import annotations

from qpane.execution.cancellation import CancellationToken


def test_subscription_fires_once_and_can_be_removed() -> None:
    """Notify active work exactly once while allowing completed work to detach."""
    token = CancellationToken()
    called: list[str] = []
    token.subscribe(lambda: called.append("active"))
    remove = token.subscribe(lambda: called.append("removed"))
    remove()

    assert token._cancel("superseded")
    assert not token._cancel("again")
    assert called == ["active"]


def test_late_subscription_observes_existing_cancellation() -> None:
    """Close the race between cancellation and native-work subscription."""
    token = CancellationToken()
    assert token._cancel("shutdown")
    called: list[bool] = []

    token.subscribe(lambda: called.append(True))

    assert called == [True]
