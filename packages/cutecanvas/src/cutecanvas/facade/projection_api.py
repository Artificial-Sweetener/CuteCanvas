#    CuteCanvas - High-performance layered image editor
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
"""Public projection commands backed by CuteCanvas's mounted QPane renderer."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QRectF, QSize
from qpane.sdk.scene import LayerPlacement

from ..document import CanvasContentKind, CanvasContentReference
from ..projection import (
    CanvasProjectionHandle,
    CanvasProjectionService,
    SceneProjectionSource,
)


class ProjectionApiMixin:
    """Expose cancellable output rendering without a second render path."""

    def requestProjection(
        self,
        reference: CanvasContentReference,
        *,
        source_bounds: QRectF | None = None,
        pixel_size: QSize | None = None,
    ) -> CanvasProjectionHandle:
        """Render current composition or layer content away from the GUI thread."""
        service = self._projection_service
        if service is None:
            service = CanvasProjectionService(
                execution_scope=self._execution_binding.scope,
                resolve_source=self._projection_source,
                is_current=self._projection_reference_is_current,
                completed=self.projectionCompleted.emit,
            )
            self._projection_service = service
        return service.request(
            reference,
            source_bounds=source_bounds,
            pixel_size=pixel_size,
        )

    def _projection_source(
        self,
        reference: CanvasContentReference,
    ) -> tuple[SceneProjectionSource, QRectF]:
        """Capture one immutable scene and its default scene-space envelope."""
        if reference.document_id != self.document().document_id:
            raise ValueError("content reference belongs to another document")
        if reference.kind is CanvasContentKind.RESOURCE:
            raise ValueError(
                "resource projection requires a composition or layer instance"
            )
        composition_id = reference.composition_id
        if composition_id is None:
            raise ValueError("projection reference has no composition")
        adapter = self._composition_scene_adapter
        rasterizer = self._scene_rasterizer
        if adapter is None or rasterizer is None:
            raise RuntimeError("canvas renderer is unavailable")
        scene = adapter.scene_for(composition_id)
        bounds = _placement_rect(scene.bounds)
        if reference.kind is CanvasContentKind.LAYER:
            layer_id = reference.layer_id
            layer = next(
                (entry for entry in scene.layers if entry.layer_id == layer_id),
                None,
            )
            if layer is None:
                raise KeyError("layer reference is no longer available")
            scene = replace(scene, layers=(layer,))
            bounds = _placement_rect(layer.placement)
        return (
            SceneProjectionSource(
                composition_id,
                (
                    reference.instance_revision,
                    reference.resource_revision,
                ),
                scene,
                rasterizer,
            ),
            bounds,
        )

    def _projection_reference_is_current(
        self,
        reference: CanvasContentReference,
    ) -> bool:
        """Return whether a stable reference still addresses its captured revision."""
        try:
            return not self.document().resolve_content(reference).stale
        except (KeyError, ValueError):
            return False


def _placement_rect(placement: LayerPlacement) -> QRectF:
    """Convert one immutable scene placement to detached Qt geometry."""
    return QRectF(
        placement.x,
        placement.y,
        placement.width,
        placement.height,
    )
