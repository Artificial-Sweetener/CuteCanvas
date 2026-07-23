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
"""Raster-oriented projection over QPane's authoritative viewer catalog."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtGui import QImage

from ..core import Config
from ..raster.image_conversion import images_differ
from ..rendering import PyramidManager
from ..rendering.sdk import RasterSource
from ..scene.identity import SourceRenderAssetKey, source_render_asset_key
from ..types import CatalogEntry
from .image_map import ImageMap
from .viewer_catalog import ViewerCatalog, ViewerCatalogEntry


@dataclass(frozen=True, slots=True)
class CatalogMutationResult:
    """Describe catalog mutation effects for cache and editor coordination."""

    removed_ids: tuple[uuid.UUID, ...] = ()
    content_changed_ids: tuple[uuid.UUID, ...] = ()
    path_changed_ids: tuple[uuid.UUID, ...] = ()
    cache_asset_keys_to_evict: tuple[SourceRenderAssetKey, ...] = ()


class ImageCatalog(QObject):
    """Project image access and revision semantics from one ``ViewerCatalog``.

    ``ViewerCatalog`` is the sole ordered-resource and selection owner. This
    adapter supplies raster pixels, revisions, and derived-product lifecycle to
    renderer and editor collaborators that do not need presentation labels.
    """

    def __init__(
        self,
        catalog: ViewerCatalog,
        pyramid_manager: PyramidManager,
        parent: QObject | None = None,
    ) -> None:
        """Bind the authoritative resource catalog and pyramid product owner."""
        super().__init__(parent)
        self._catalog = catalog
        self.pyramid_manager = pyramid_manager

    @property
    def resources(self) -> ViewerCatalog:
        """Return the authoritative ordered resource owner."""
        return self._catalog

    def apply_config(self, config: Config) -> None:
        """Apply renderer settings and refresh the selected pyramid product."""
        self.pyramid_manager.apply_config(config)
        current = self._catalog.current
        if current is not None:
            self._warm(current)

    def setImagesByID(
        self,
        image_map: ImageMap,
        current_id: uuid.UUID,
    ) -> CatalogMutationResult:
        """Atomically replace resources while preserving content revisions."""
        if not image_map:
            raise ValueError("image_map must not be empty")
        if current_id not in image_map:
            raise KeyError("current_id must be a key in image_map")
        previous = {entry.entry_id: entry for entry in self._catalog.entries}
        next_entries: list[ViewerCatalogEntry] = []
        changed_ids: list[uuid.UUID] = []
        path_ids: list[uuid.UUID] = []
        evicted: list[SourceRenderAssetKey] = []
        for image_id, value in image_map.items():
            if not isinstance(value, CatalogEntry):
                raise TypeError("image_map values must be CatalogEntry instances")
            if not isinstance(value.image, QImage):
                raise TypeError("CatalogEntry.image must be a QImage instance")
            image = self._ensure_argb32(value.image)
            old = previous.get(image_id)
            old_image = self._entry_image(old)
            content_changed = images_differ(old_image, image)
            path_changed = old is not None and old.path != value.path
            if content_changed:
                changed_ids.append(image_id)
            if path_changed:
                path_ids.append(image_id)
            if old is not None and (content_changed or path_changed):
                evicted.append(self._key(old))
            revision = (
                1
                if old is None
                else old.source.revision + (1 if content_changed else 0)
            )
            source = RasterSource.from_image(
                image,
                source_id=image_id,
                revision=revision,
                path=value.path,
                source_kind="catalog-image",
            )
            next_entries.append(
                ViewerCatalogEntry(
                    source=source,
                    label=self._label(value.path, image_id),
                    path=value.path,
                )
            )
        removed_ids = tuple(
            entry_id for entry_id in previous if entry_id not in image_map
        )
        for entry_id in removed_ids:
            evicted.append(self._key(previous[entry_id]))
        self._remove_products(evicted)
        self._catalog.replace_all(tuple(next_entries), current_id)
        for entry in next_entries:
            self._warm(entry)
        return CatalogMutationResult(
            removed_ids=removed_ids,
            content_changed_ids=tuple(changed_ids),
            path_changed_ids=tuple(path_ids),
            cache_asset_keys_to_evict=tuple(dict.fromkeys(evicted)),
        )

    def addImage(
        self,
        image_id: uuid.UUID,
        image: QImage,
        path: Path | None,
    ) -> CatalogMutationResult:
        """Add or update one source without changing active selection."""
        if not isinstance(image, QImage) or image.isNull():
            raise ValueError("image must not be null")
        formatted = self._ensure_argb32(image)
        old = self._catalog.entry(image_id)
        content_changed = images_differ(self._entry_image(old), formatted)
        path_changed = old is not None and old.path != path
        evicted = (
            (self._key(old),)
            if old is not None and (content_changed or path_changed)
            else ()
        )
        self._remove_products(evicted)
        revision = (
            1 if old is None else old.source.revision + (1 if content_changed else 0)
        )
        source = RasterSource.from_image(
            formatted,
            source_id=image_id,
            revision=revision,
            path=path,
            source_kind="catalog-image",
        )
        if old is None:
            entry = self._catalog.add_source(
                source,
                label=self._label(path, image_id),
                path=path,
                select=False,
            )
        else:
            _previous, entry = self._catalog.replace_source(
                source,
                label=old.label,
                path=path,
            )
        self._warm(entry)
        return CatalogMutationResult(
            content_changed_ids=(image_id,) if content_changed else (),
            path_changed_ids=(image_id,) if path_changed else (),
            cache_asset_keys_to_evict=evicted,
        )

    def updateCurrentEntry(
        self,
        *,
        image: QImage | None = None,
        path: Path | None = None,
    ) -> CatalogMutationResult:
        """Replace selected pixels and/or path while retaining resource identity."""
        current = self._catalog.current
        if current is None:
            return CatalogMutationResult()
        previous_image = self._entry_image(current)
        formatted = (
            previous_image
            if image is None or image.isNull()
            else self._ensure_argb32(image)
        )
        if formatted is None:
            return CatalogMutationResult()
        content_changed = image is not None and images_differ(previous_image, formatted)
        path_changed = current.path != path
        if not content_changed and not path_changed:
            return CatalogMutationResult()
        old_key = self._key(current)
        self._remove_products((old_key,))
        source = RasterSource.from_image(
            formatted,
            source_id=current.entry_id,
            revision=current.source.revision + (1 if content_changed else 0),
            path=path,
            source_kind="catalog-image",
        )
        _previous, replacement = self._catalog.replace_source(
            source,
            label=current.label,
            path=path,
        )
        self._warm(replacement)
        return CatalogMutationResult(
            content_changed_ids=(current.entry_id,) if content_changed else (),
            path_changed_ids=(current.entry_id,) if path_changed else (),
            cache_asset_keys_to_evict=(old_key,),
        )

    def removeImageByID(self, image_id: uuid.UUID) -> None:
        """Remove one resource and its derived pyramid product."""
        entry = self._catalog.entry(image_id)
        if entry is None:
            raise KeyError("image_id not found")
        self._remove_products((self._key(entry),))
        self._catalog.remove(image_id)

    def clearImages(self) -> None:
        """Remove every resource and only its own derived products."""
        self._remove_products(
            tuple(self._key(entry) for entry in self._catalog.entries)
        )
        self._catalog.clear()

    def setCurrentImageID(self, image_id: uuid.UUID | None) -> None:
        """Select one resource or retain resources while deselecting all."""
        if image_id is None:
            self._catalog.deselect()
            return
        self._catalog.select_entry(image_id)

    def getImage(self, image_id: uuid.UUID) -> QImage | None:
        """Return detached implicitly-shared pixels for one resource."""
        return self._entry_image(self._catalog.entry(image_id))

    def getPath(self, image_id: uuid.UUID) -> Path | None:
        """Return optional source provenance for one resource."""
        entry = self._catalog.entry(image_id)
        return None if entry is None else entry.path

    def getRevision(self, image_id: uuid.UUID) -> int | None:
        """Return the monotonic pixel revision for one resource."""
        entry = self._catalog.entry(image_id)
        return None if entry is None else entry.source.revision

    def defaultAssetKeyForImage(
        self,
        image_id: uuid.UUID,
    ) -> SourceRenderAssetKey | None:
        """Return reusable renderer-product identity for one resource."""
        entry = self._catalog.entry(image_id)
        return None if entry is None else self._key(entry)

    def getCurrentImage(self) -> QImage | None:
        """Return pixels for the selected resource when present."""
        return self._entry_image(self._catalog.current)

    def getCurrentPath(self) -> Path | None:
        """Return path metadata for the selected resource when present."""
        current = self._catalog.current
        return None if current is None else current.path

    def getCurrentId(self) -> uuid.UUID | None:
        """Return selected source identity when present."""
        current = self._catalog.current
        return None if current is None else current.entry_id

    def getCurrentRevision(self) -> int | None:
        """Return selected source pixel revision when present."""
        current = self._catalog.current
        return None if current is None else current.source.revision

    def containsImage(self, image_id: uuid.UUID) -> bool:
        """Return whether one resource identity exists."""
        return self._catalog.entry(image_id) is not None

    def getImageIds(self) -> list[uuid.UUID]:
        """Return source identities in authoritative display order."""
        return [entry.entry_id for entry in self._catalog.entries]

    def hasImages(self) -> bool:
        """Return whether the resource catalog is non-empty."""
        return bool(self._catalog.entries)

    def getAllImages(self) -> list[QImage]:
        """Return all available pixels in authoritative order."""
        return [
            image
            for entry in self._catalog.entries
            if (image := self._entry_image(entry)) is not None
        ]

    def getAllPaths(self) -> list[Path | None]:
        """Return paths aligned with the authoritative resource order."""
        return [entry.path for entry in self._catalog.entries]

    def getBestFitImageForAsset(
        self,
        asset_key: SourceRenderAssetKey | None,
        target_width: float,
    ) -> QImage | None:
        """Return the best available shared pyramid level for an asset."""
        if asset_key is None:
            return None
        return self.pyramid_manager.get_best_fit_image_for_asset(
            asset_key,
            target_width,
        )

    def _warm(self, entry: ViewerCatalogEntry) -> None:
        """Schedule one source pyramid using the shared renderer owner."""
        image = self._entry_image(entry)
        if image is not None and not image.isNull():
            self.pyramid_manager.generate_pyramid_for_asset(self._key(entry), image)

    def _remove_products(self, keys: tuple[SourceRenderAssetKey, ...]) -> None:
        """Evict only products belonging to replaced or removed resources."""
        for key in dict.fromkeys(keys):
            self.pyramid_manager.remove_pyramid(key)

    @staticmethod
    def _entry_image(entry: ViewerCatalogEntry | None) -> QImage | None:
        """Resolve one entry's public raster provider into detached pixels."""
        if entry is None:
            return None
        image = entry.source.provider.image(None)
        return None if image is None or image.isNull() else QImage(image)

    @staticmethod
    def _key(entry: ViewerCatalogEntry) -> SourceRenderAssetKey:
        """Return the resource's reusable product identity."""
        source = entry.source
        return source_render_asset_key(
            source_id=source.source_id,
            source_kind=source.source_kind,
            revision=source.revision,
            source_path=source.path,
        )

    @staticmethod
    def _label(path: Path | None, image_id: uuid.UUID) -> str:
        """Return stable presentation metadata for editor-projected resources."""
        return path.name if path is not None else str(image_id)

    @staticmethod
    def _ensure_argb32(image: QImage) -> QImage:
        """Normalize pixels for predictable raster rendering."""
        if image.isNull() or image.format() == QImage.Format_ARGB32_Premultiplied:
            return image
        return image.convertToFormat(QImage.Format_ARGB32_Premultiplied)
