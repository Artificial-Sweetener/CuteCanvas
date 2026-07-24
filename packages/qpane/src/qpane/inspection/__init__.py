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
"""Normalized inspection contracts and state coordination."""

from .model import (
    InspectionRegion,
    InspectionTarget,
    InspectionUpdate,
    InspectionViewState,
    InspectionZoomMode,
    ProjectedViewport,
)
from .projection import capture_inspection, project_inspection
from .store import InspectionObserver, InspectionStateStore

__all__ = [
    "InspectionObserver",
    "InspectionRegion",
    "InspectionStateStore",
    "InspectionTarget",
    "InspectionUpdate",
    "InspectionViewState",
    "InspectionZoomMode",
    "ProjectedViewport",
    "capture_inspection",
    "project_inspection",
]
