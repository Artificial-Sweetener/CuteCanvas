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
"""Lazily expose catalog collaborators without importing rendering eagerly."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .viewer_catalog import ViewerCatalog as ViewerCatalog
    from .viewer_catalog import ViewerCatalogEntry as ViewerCatalogEntry
    from .viewer_content import ViewerContent as ViewerContent
    from .viewer_navigation import ViewerNavigation as ViewerNavigation
    from .viewer_placeholder import ViewerPlaceholder as ViewerPlaceholder
    from .viewer_placeholder import ViewerPlaceholderState as ViewerPlaceholderState
    from .viewer_prefetch import ViewerPrefetch as ViewerPrefetch
    from .viewer_prefetch import ViewerPrefetchSnapshot as ViewerPrefetchSnapshot

_EXPORTS = {
    "ViewerCatalog": (".viewer_catalog", "ViewerCatalog"),
    "ViewerCatalogEntry": (".viewer_catalog", "ViewerCatalogEntry"),
    "ViewerContent": (".viewer_content", "ViewerContent"),
    "ViewerNavigation": (".viewer_navigation", "ViewerNavigation"),
    "ViewerPrefetch": (".viewer_prefetch", "ViewerPrefetch"),
    "ViewerPrefetchSnapshot": (".viewer_prefetch", "ViewerPrefetchSnapshot"),
    "ViewerPlaceholder": (".viewer_placeholder", "ViewerPlaceholder"),
    "ViewerPlaceholderState": (".viewer_placeholder", "ViewerPlaceholderState"),
}

__all__ = tuple(_EXPORTS)


def __getattr__(name: str) -> object:
    """Load one catalog collaborator only when requested."""
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(target[0], __name__), target[1])
    globals()[name] = value
    return value
