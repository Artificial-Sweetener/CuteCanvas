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
"""Expose QPane's supported advanced integration namespaces.

The ordinary :mod:`qpane` facade remains the ergonomic entry point for viewers
and declarative scenes.  These focused namespaces are the stable boundary for
hosts that integrate directly with QPane's renderer infrastructure.
"""

from . import (
    cache,
    catalog,
    compare,
    concurrency,
    configuration,
    diagnostics,
    features,
    inspection,
    layout,
    overlays,
    raster,
    rendering,
    scene,
    system,
    types,
    ui,
    vector,
)

__all__ = (
    "cache",
    "catalog",
    "compare",
    "concurrency",
    "configuration",
    "diagnostics",
    "features",
    "inspection",
    "layout",
    "overlays",
    "raster",
    "rendering",
    "scene",
    "system",
    "types",
    "ui",
    "vector",
)
