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
"""Shared snapping engine for CuteCanvas editor interactions."""

from .configuration import SnapConfiguration, SnapPolicy
from .engine import SnapEngine, SnapSession
from .model import (
    SnapAxis,
    SnapCandidate,
    SnapFeatureKind,
    SnapGrid,
    SnapGuide,
    SnapResult,
    bounds_candidates,
)

__all__ = [
    "SnapAxis",
    "SnapCandidate",
    "SnapConfiguration",
    "SnapEngine",
    "SnapFeatureKind",
    "SnapGrid",
    "SnapGuide",
    "SnapPolicy",
    "SnapResult",
    "SnapSession",
    "bounds_candidates",
]
