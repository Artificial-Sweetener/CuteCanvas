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
"""Supported renderer host objects and detached rasterization functions."""

from ..rendering import (
    PyramidManager,
    Renderer,
    RenderingPresenter,
    View,
    ViewportZoomMode,
)
from ..rendering.coordinates import PanelHitTest
from ..rendering.layer_rasterization import (
    rasterize_layer,
    rasterize_region,
)
from ..rendering.render_tile_geometry import RenderTileRequest
from ..rendering.render_tile_types import (
    RegionSampleSource,
    RenderTileBatchSource,
    RenderTileProduct,
)
from ..rendering.scene_coordinates import (
    LayerCoordinateProjection,
    LayerLocalPoint,
    LayerSourcePoint,
    PanelPoint,
    SceneCoordinateProjection,
    SceneCoordinateSystem,
    ScenePoint,
)
from ..rendering.scene_region import (
    RasterLayerRegionOverride,
    SceneLayerRenderScope,
    SceneRegionRasterizer,
)

__all__ = (
    "LayerCoordinateProjection",
    "LayerLocalPoint",
    "LayerSourcePoint",
    "PanelHitTest",
    "PanelPoint",
    "PyramidManager",
    "RasterLayerRegionOverride",
    "RegionSampleSource",
    "RenderTileBatchSource",
    "RenderTileProduct",
    "RenderTileRequest",
    "Renderer",
    "RenderingPresenter",
    "SceneCoordinateProjection",
    "SceneCoordinateSystem",
    "SceneLayerRenderScope",
    "ScenePoint",
    "SceneRegionRasterizer",
    "View",
    "ViewportZoomMode",
    "rasterize_layer",
    "rasterize_region",
)
