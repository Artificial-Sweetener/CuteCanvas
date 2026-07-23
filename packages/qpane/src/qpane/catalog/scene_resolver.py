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
"""Resolve the viewer's active catalog, replacement, or placeholder scene."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QSize
from PySide6.QtGui import QImage

from ..scene.assembly import SceneAssembly
from ..scene.model import SceneDescriptor
from ..scene.placeholder_scene import build_placeholder_scene
from ..scene.registry import SceneProviderRegistry


class ViewerSceneCatalog(Protocol):
    """Expose catalog state needed to select the viewer's active scene."""

    def getCurrentId(self) -> uuid.UUID | None:
        """Return the selected catalog image identity."""

    def getCurrentImage(self) -> QImage | None:
        """Return the selected catalog image."""

    def getCurrentPath(self) -> Path | None:
        """Return the selected catalog path when known."""

    def getRevision(self, image_id: uuid.UUID) -> int | None:
        """Return the content revision for one catalog image."""


class CatalogSceneResolver:
    """Own viewer-specific active scene selection outside rendering."""

    def __init__(
        self,
        catalog: ViewerSceneCatalog,
        providers: SceneProviderRegistry,
    ) -> None:
        """Capture catalog state and registered scene contributions."""
        self._catalog = catalog
        self._providers = providers
        self._assembly = SceneAssembly(providers)
        self._placeholder_provider: Callable[[], object | None] = lambda: None

    def set_placeholder_provider(
        self,
        provider: Callable[[], object | None],
    ) -> None:
        """Install the catalog-owned placeholder content provider."""
        self._placeholder_provider = provider

    def scene(self) -> SceneDescriptor | None:
        """Return the active replacement, catalog, or placeholder scene."""
        replacement = self._assembly.resolve_replacement()
        if replacement is not None:
            return replacement
        image_id = self._catalog.getCurrentId()
        image = self._catalog.getCurrentImage()
        if image_id is not None and image is not None and not image.isNull():
            return self._assembly.resolve_catalog_image(
                image_id=image_id,
                image_size=image.size(),
                source_path=self._catalog.getCurrentPath(),
                source_revision=self._catalog_revision(image_id),
            )
        return self._placeholder_scene()

    def revision(self) -> tuple[object, ...]:
        """Return all viewer state that can change the active scene."""
        image_id = self._catalog.getCurrentId()
        placeholder = self._placeholder_provider()
        placeholder_image = getattr(placeholder, "image", None)
        placeholder_size = (
            QSize(placeholder_image.size())
            if isinstance(placeholder_image, QImage) and not placeholder_image.isNull()
            else QSize()
        )
        placeholder_revision = max(
            0,
            int(getattr(placeholder, "revision", 0) or 0),
        )
        return (
            image_id,
            self._catalog.getCurrentPath() if image_id is not None else None,
            self._catalog_revision(image_id),
            placeholder is not None,
            getattr(placeholder, "source_path", None),
            placeholder_size.width(),
            placeholder_size.height(),
            placeholder_revision,
            self._providers.revision(),
        )

    def _placeholder_scene(self) -> SceneDescriptor | None:
        """Build a scene for configured placeholder pixels when available."""
        placeholder = self._placeholder_provider()
        image = getattr(placeholder, "image", None)
        if not isinstance(image, QImage) or image.isNull():
            return None
        source_path = getattr(placeholder, "source_path", None)
        revision = max(0, int(getattr(placeholder, "revision", 0) or 0))
        return build_placeholder_scene(
            image_size=QSize(image.size()),
            source_path=source_path,
            revision=revision,
        )

    def _catalog_revision(self, image_id: uuid.UUID | None) -> int:
        """Return a normalized revision for the selected catalog image."""
        if image_id is None:
            return 0
        return max(0, int(self._catalog.getRevision(image_id) or 0))
