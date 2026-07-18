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

"""Expose SAM integration helpers for QPane."""

from . import service
from .delegate import SamDelegate
from .manager import (
    SamManager,
    SamPredictorMetrics,
    SamWorker,
    SamWorkerSignals,
)

__all__ = (
    "SamDelegate",
    "SamManager",
    "SamPredictorMetrics",
    "SamWorker",
    "SamWorkerSignals",
    "service",
)
