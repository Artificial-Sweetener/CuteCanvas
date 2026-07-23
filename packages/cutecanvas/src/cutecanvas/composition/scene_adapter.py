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

"""Adapt stored layered compositions into internal scene contributions."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QRectF
from qpane.sdk.catalog import CatalogImageReference
from qpane.sdk.scene import (
    LayerPlacement,
    SceneContribution,
    SceneDescriptor,
    SceneKind,
    SceneLayerHitTestResult,
)

from ..scene.layer_assembly import CompositionLayerSceneAssembler
from ..types import LayerHit
from .layers import CompositionLayerInstance
from .model import CompositionRecord
from .service import CompositionService

_LAYERED_COMPOSITION_ORDER = -30


class CompositionSceneAdapter:
    """Expose the active layered composition as private scene-provider data."""

    def __init__(
        self,
        *,
        compositions: CompositionService,
        assembler: CompositionLayerSceneAssembler,
    ) -> None:
        """Capture document and cross-domain assembly collaborators."""
        self._compositions = compositions
        self._assembler = assembler

    def scene_contribution(self) -> SceneContribution | None:
        """Return the active composition document as a replacement contribution."""
        record = self._active_record()
        if record is None:
            return None
        document = SceneDescriptor(
            scene_id=record.composition_id,
            kind=SceneKind.EXPLICIT,
            bounds=_placement_from_rect(record.canvas_bounds),
            layers=(),
        )
        scene = self._assembler.assemble(document)
        return SceneContribution(scene=scene, order=_LAYERED_COMPOSITION_ORDER)

    def revision(self) -> tuple[object, ...]:
        """Return revisions that can change the replacement scene contribution."""
        record = self._active_record()
        if record is None:
            return (self._compositions.revision(), None)
        return (
            self._compositions.revision(),
            self._assembler.revision(),
        )

    def hit_from_result(
        self, result: SceneLayerHitTestResult | None
    ) -> LayerHit | None:
        """Map an internal scene-layer hit to the active composition snapshot."""
        record = self._active_record()
        if record is None or result is None:
            return None
        if result.scene_id != record.composition_id:
            return None
        layer = self._record_layer_for_id(record, result.layer_id)
        if layer is None:
            return None
        return LayerHit(
            composition_id=record.composition_id,
            scene_id=record.composition_id,
            layer_id=result.layer_id,
            image_id=(
                layer.source.image_id
                if isinstance(layer.source, CatalogImageReference)
                else None
            ),
            role=layer.role,
            metadata=layer.metadata,
            panel_point=result.panel_point,
            scene_point=result.scene_point,
            source_point=result.source_point,
        )

    def _active_record(self) -> CompositionRecord | None:
        """Return the active composition document, if one is active."""
        return self._compositions.active_record()

    def _record_layer_for_id(
        self, record: CompositionRecord, layer_id: uuid.UUID
    ) -> CompositionLayerInstance | None:
        """Return the stored layer with ``layer_id`` from ``record``."""
        return self._compositions.layers.layer(
            record.composition_id,
            layer_id,
        )


def _placement_from_rect(rect: QRectF) -> LayerPlacement:
    """Convert a Qt rectangle to internal scene placement."""
    return LayerPlacement(
        x=rect.x(),
        y=rect.y(),
        width=rect.width(),
        height=rect.height(),
    )
