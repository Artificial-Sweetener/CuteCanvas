#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Catalog-owned metadata, raster, and hit-test source capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QPointF, QSize
from PySide6.QtGui import QImage

from ..scene.source_capabilities import RasterPresentation, RasterProductPolicy
from ..scene.source_references import LayerSourceReference
from .source_reference import CatalogImageReference


@dataclass(frozen=True, slots=True)
class CatalogSourceCapabilities:
    """Adapt catalog authority to focused scene-source contracts."""

    catalog: object

    @property
    def presentation(self) -> RasterPresentation:
        """Return ordinary image-raster presentation."""
        return RasterPresentation.IMAGE

    def product_policy(self, source: LayerSourceReference) -> RasterProductPolicy:
        """Return the stable shared-product policy for catalog pixels."""
        return RasterProductPolicy.CACHEABLE

    def source_image(
        self,
        source: LayerSourceReference,
        *,
        scale: float | None = None,
    ) -> QImage | None:
        """Return catalog pixels for ``source``."""
        if not isinstance(source, CatalogImageReference):
            return None
        image_getter = getattr(self.catalog, "getImage", None)
        return None if not callable(image_getter) else image_getter(source.image_id)

    def source_size(self, source: LayerSourceReference) -> QSize | None:
        """Return catalog dimensions from its owned image."""
        image = self.source_image(source)
        return None if image is None or image.isNull() else image.size()

    def source_path(self, source: LayerSourceReference) -> Path | None:
        """Return the catalog path for ``source``."""
        if not isinstance(source, CatalogImageReference):
            return None
        path_getter = getattr(self.catalog, "getPath", None)
        return None if not callable(path_getter) else path_getter(source.image_id)

    def contains(self, source: LayerSourceReference, point: QPointF) -> bool:
        """Treat catalog image bounds as fully occupied after geometry clipping."""
        return isinstance(source, CatalogImageReference)
