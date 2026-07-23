#    QPane + CuteCanvas - High-performance PySide6 rendering and editing
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
"""Tests for source-neutral raster pyramid selection and invalidation."""

import uuid

from PySide6.QtGui import QImage
from qpane.rendering.raster_products import RasterRenderProductStore
from qpane.scene.identity import SourceRenderAssetKey


class _PyramidProducts:
    """Record raster-product operations without background workers."""

    def __init__(self) -> None:
        """Initialize empty product state."""
        self.images: dict[SourceRenderAssetKey, QImage] = {}
        self.generated: list[SourceRenderAssetKey] = []
        self.removed: list[SourceRenderAssetKey] = []

    def pyramid_for_asset(self, asset_key: SourceRenderAssetKey) -> object | None:
        """Return retained state when generated."""
        return self.images.get(asset_key)

    def generate_pyramid_for_asset(
        self,
        asset_key: SourceRenderAssetKey,
        image: QImage,
    ) -> None:
        """Retain the supplied full product."""
        self.generated.append(asset_key)
        self.images[asset_key] = QImage(image)

    def get_best_fit_image_for_asset(
        self,
        asset_key: SourceRenderAssetKey,
        target_width: float,
    ) -> QImage | None:
        """Return the retained product."""
        return self.images.get(asset_key)

    def remove_pyramid(self, asset_key: SourceRenderAssetKey) -> None:
        """Remove one retained product."""
        self.removed.append(asset_key)
        self.images.pop(asset_key, None)


class _TileProducts:
    """Record source-oriented tile invalidation."""

    def __init__(self) -> None:
        """Initialize without removals."""
        self.removed: list[SourceRenderAssetKey] = []

    def remove_tiles_for_source_asset(
        self,
        asset_key: SourceRenderAssetKey,
    ) -> None:
        """Record one source invalidation."""
        self.removed.append(asset_key)


def _key(source_id: uuid.UUID, kind: str, revision: int) -> SourceRenderAssetKey:
    """Return a source-product identity for one test revision."""
    return SourceRenderAssetKey(source_id, kind, revision)


def test_every_raster_kind_uses_the_same_lazy_product_selection() -> None:
    """Catalog, editable, placed, and coverage sources share one product policy."""
    pyramids = _PyramidProducts()
    tiles = _TileProducts()
    products = RasterRenderProductStore(pyramids, tiles)
    source = QImage(128, 64, QImage.Format_ARGB32_Premultiplied)

    keys = tuple(
        _key(uuid.uuid4(), kind, 0) for kind in ("catalog", "raster", "placed", "mask")
    )
    selected = tuple(
        products.best_fit_image(asset_key=key, full_image=source, target_width=32.0)
        for key in keys
    )

    assert all(not image.isNull() for image in selected)
    assert pyramids.generated == list(keys)
    assert tiles.removed == []


def test_new_source_revision_invalidates_pyramids_and_tiles_once() -> None:
    """A source edit drops stale products without coupling invalidation to its domain."""
    pyramids = _PyramidProducts()
    tiles = _TileProducts()
    products = RasterRenderProductStore(pyramids, tiles)
    source_id = uuid.uuid4()
    first = _key(source_id, "raster", 4)
    second = _key(source_id, "raster", 5)
    source = QImage(64, 64, QImage.Format_ARGB32_Premultiplied)

    products.best_fit_image(asset_key=first, full_image=source, target_width=16.0)
    products.best_fit_image(asset_key=first, full_image=source, target_width=16.0)
    products.best_fit_image(asset_key=second, full_image=source, target_width=16.0)

    assert pyramids.generated == [first, second]
    assert pyramids.removed == [first]
    assert tiles.removed == [first]


def test_pending_pyramid_uses_one_bounded_preview_product() -> None:
    """A large source must never be painted full-size while its pyramid is pending."""
    pyramids = _PyramidProducts()
    tiles = _TileProducts()
    products = RasterRenderProductStore(pyramids, tiles)
    source = QImage(4096, 2048, QImage.Format_ARGB32_Premultiplied)
    key = _key(uuid.uuid4(), "raster", 1)

    first = products.best_fit_image(
        asset_key=key,
        full_image=source,
        target_width=300.0,
    )
    second = products.best_fit_image(
        asset_key=key,
        full_image=source,
        target_width=300.0,
    )

    assert first.width() == 512
    assert first.height() == 256
    assert second.cacheKey() == first.cacheKey()
    assert products.usage_bytes == first.sizeInBytes()


def test_sparse_display_sample_is_reused_until_source_revision_changes() -> None:
    """Pointer frames must not resample unchanged sparse authoritative pixels."""
    pyramids = _PyramidProducts()
    tiles = _TileProducts()
    products = RasterRenderProductStore(pyramids, tiles)
    source_id = uuid.uuid4()
    first_key = _key(source_id, "raster", 3)
    second_key = _key(source_id, "raster", 4)
    calls: list[float] = []

    def produce(scale: float) -> QImage:
        """Record one source-owned sparse sampling request."""
        calls.append(scale)
        return QImage(512, 256, QImage.Format_ARGB32_Premultiplied)

    first = products.sampled_image(
        asset_key=first_key,
        source_width=8192,
        target_width=500.0,
        producer=produce,
    )
    repeated = products.sampled_image(
        asset_key=first_key,
        source_width=8192,
        target_width=500.0,
        producer=produce,
    )
    advanced = products.sampled_image(
        asset_key=second_key,
        source_width=8192,
        target_width=500.0,
        producer=produce,
    )

    assert first is not None and repeated is not None and advanced is not None
    assert first.cacheKey() == repeated.cacheKey()
    assert len(calls) == 2
    assert tiles.removed == [first_key]
