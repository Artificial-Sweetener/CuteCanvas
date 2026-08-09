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
"""Resolve source-native navigation from the visible scene layer under input."""

from __future__ import annotations

from collections.abc import Callable
from math import isfinite

from PySide6.QtCore import QPointF

from ..rendering.scene_hit_testing import SceneRenderHitTester
from ..rendering.sdk import RenderScene
from ..scene.mapping import LayerMapping, conservative_mapping_scale
from ..scene.raster import RasterBounds
from ..scene.render_plan import SceneRenderItem, SceneRenderPlan

_MAXIMUM_RELATIVE_ZOOM = 10.0


class SceneNativeZoomResolver:
    """Derive source-relative zoom semantics from the active rendered scene."""

    def __init__(
        self,
        plan_provider: Callable[[], SceneRenderPlan | None],
        scene_provider: Callable[[], RenderScene | None],
        fallback_native_zoom: Callable[[], float],
    ) -> None:
        """Bind current frame geometry and the base scene-native zoom."""

        self._plan_provider = plan_provider
        self._scene_provider = scene_provider
        self._fallback_native_zoom = fallback_native_zoom
        self._hit_tester = SceneRenderHitTester()

    def native_zoom_at(self, panel_point: QPointF) -> float:
        """Return the zoom where the visible source reaches native pixel scale."""

        fallback = self._safe_fallback()
        plan = self._plan_provider()
        if plan is None:
            return fallback
        for item in reversed(plan.render_items):
            hit = self._hit_tester.hit_test(plan, item, panel_point)
            if hit is None:
                continue
            return self._native_zoom_for_item(item, fallback)
        return fallback

    def maximum_zoom(self) -> float:
        """Return the ceiling where the slowest comparison source reaches 1000%."""

        fallback = self._safe_fallback()
        scene = self._scene_provider()
        if scene is None or not any(
            layer.role == "comparison-image" for layer in scene.layers
        ):
            return fallback * _MAXIMUM_RELATIVE_ZOOM
        native_zooms = tuple(
            self._native_zoom_for_transform(
                layer.transform,
                layer.source.bounds,
                fallback,
            )
            for layer in scene.layers
        )
        return max(native_zooms, default=fallback) * _MAXIMUM_RELATIVE_ZOOM

    @staticmethod
    def _native_zoom_for_item(item: SceneRenderItem, fallback: float) -> float:
        """Return finite source-native zoom from one render item's scene transform."""

        return SceneNativeZoomResolver._native_zoom_for_transform(
            item.descriptor.transform,
            item.descriptor.raster_bounds,
            fallback,
        )

    @staticmethod
    def _native_zoom_for_transform(
        transform: LayerMapping | None,
        bounds: RasterBounds | None,
        fallback: float,
    ) -> float:
        """Return finite source-native zoom from one source-to-scene transform."""

        if transform is None or bounds is None:
            return fallback
        source_scale = conservative_mapping_scale(transform, bounds)
        if not isfinite(source_scale) or source_scale <= 0.0:
            return fallback
        return fallback / source_scale

    def _safe_fallback(self) -> float:
        """Return one finite positive scene-native zoom."""

        fallback = float(self._fallback_native_zoom())
        return fallback if isfinite(fallback) and fallback > 0.0 else 1.0


__all__ = ["SceneNativeZoomResolver"]
