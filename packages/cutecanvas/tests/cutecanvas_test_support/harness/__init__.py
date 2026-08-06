#    CuteCanvas - High-performance layered image editor
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

"""Reusable mounted-widget infrastructure for CuteCanvas system tests."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .mounted_qpane import MountedQPaneHarness, PixelMeasurement
    from .pointer_transition_probe import (
        PointerEventObservation,
        PointerTransitionProbe,
    )
    from .release_probe import (
        ReleaseFrame,
        ReleaseTransition,
        ReleaseTransitionProbe,
    )

__all__ = [
    "MountedQPaneHarness",
    "PixelMeasurement",
    "PointerEventObservation",
    "PointerTransitionProbe",
    "ReleaseFrame",
    "ReleaseTransition",
    "ReleaseTransitionProbe",
]

_PUBLIC_MODULES = {
    "MountedQPaneHarness": ".mounted_qpane",
    "PixelMeasurement": ".mounted_qpane",
    "PointerEventObservation": ".pointer_transition_probe",
    "PointerTransitionProbe": ".pointer_transition_probe",
    "ReleaseFrame": ".release_probe",
    "ReleaseTransition": ".release_probe",
    "ReleaseTransitionProbe": ".release_probe",
}


def __getattr__(name: str) -> Any:
    """Load public harness types without burdening command-line bootstrap."""
    try:
        module_name = _PUBLIC_MODULES[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value
