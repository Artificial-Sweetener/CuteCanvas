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
"""Tests for editable-raster source revision publication."""

from __future__ import annotations

import numpy as np
from cutecanvas.raster.assets import EditableRasterAssetStore
from cutecanvas.raster.descriptor_factory import EditableRasterLayerDescriptorFactory
from cutecanvas.raster.presentation_state import EditableRasterPresentationState
from cutecanvas.raster.source_reference import EditableRasterReference
from cutecanvas.raster.source_resolver import EditableRasterSourceCapabilities
from cutecanvas.types import RasterExtentPolicy
from PySide6.QtGui import QColor, QImage
from qpane.scene.raster import RasterBounds
from qpane.scene.source_capabilities import RasterProductPolicy


def test_store_revision_tracks_content_and_structure_mutations() -> None:
    """Every render-affecting asset mutation must invalidate scene descriptors."""
    image = QImage(8, 6, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor(20, 40, 60, 255))
    assets = EditableRasterAssetStore()
    asset = assets.create(image)
    factory = EditableRasterLayerDescriptorFactory(assets)
    initial_revision = factory.revision()

    replacement = np.zeros((2, 3, 4), dtype=np.uint8)
    assert asset.surface.restore_patch(RasterBounds(1, 2, 3, 2), replacement)
    content_revision = factory.revision()

    assert content_revision != initial_revision
    assert asset.surface.set_extent_policy(RasterExtentPolicy.EXPAND_ON_WRITE)
    structure_revision = factory.revision()

    assert structure_revision != content_revision
    assert structure_revision == ((asset.raster_id, *asset.surface.revisions()),)


def test_store_revision_tracks_asset_lifecycle() -> None:
    """Creation and removal must also advance the descriptor registry identity."""
    assets = EditableRasterAssetStore()
    initial_revision = assets.revision
    image = QImage(4, 4, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor(0, 0, 0, 0))

    asset = assets.create(image)
    created_revision = assets.revision
    assert created_revision != initial_revision

    assert assets.remove(asset.raster_id)
    assert assets.revision == initial_revision


def test_live_raster_transaction_bypasses_derived_products_until_settled() -> None:
    """Interactive pixels must not rebuild pyramids for every pointer sample."""
    assets = EditableRasterAssetStore()
    image = QImage(8, 8, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor(10, 20, 30, 255))
    asset = assets.create(image)
    source = EditableRasterReference(asset.raster_id)
    presentation = EditableRasterPresentationState()
    capabilities = EditableRasterSourceCapabilities(assets, presentation)

    assert capabilities.product_policy(source) is RasterProductPolicy.CACHEABLE
    presentation.begin(asset.raster_id)
    assert capabilities.product_policy(source) is RasterProductPolicy.VOLATILE
    presentation.end(asset.raster_id)
    assert capabilities.product_policy(source) is RasterProductPolicy.CACHEABLE
