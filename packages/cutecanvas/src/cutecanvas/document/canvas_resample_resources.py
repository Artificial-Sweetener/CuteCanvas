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
"""Resource capture and installation for whole-canvas resampling."""

from __future__ import annotations

import uuid

from PySide6.QtGui import QImage
from qpane.sdk.scene import LayerTransform

from ..composition.layers import CompositionLayerInstance
from ..coverage import CoverageAssetSnapshot
from ..masks.mask import MaskAssetStore
from ..placed.model import PlacedAssetSnapshot
from ..raster.sparse_grid import SparseRasterSnapshot
from ..resources import ProjectResourceKind, ProjectResourceReference
from ..resources.document_core import DocumentResourceCore
from .canvas_resampling import (
    CanvasResampleResourceInput,
    CanvasResampleResourceProduct,
)

RasterSourceSnapshot = (
    SparseRasterSnapshot | PlacedAssetSnapshot | CoverageAssetSnapshot
)


class CanvasResampleResourceOwner:
    """Own copy-on-write raster resource capture and installation."""

    def __init__(
        self,
        document: DocumentResourceCore,
        masks: MaskAssetStore,
    ) -> None:
        """Bind the resource registries that own resampled payloads."""
        self._document = document
        self._masks = masks

    def capture(
        self,
        layers: tuple[CompositionLayerInstance, ...],
        scale: LayerTransform,
    ) -> tuple[
        tuple[CanvasResampleResourceInput, ...],
        dict[uuid.UUID, uuid.UUID],
        int,
    ]:
        """Capture each directly raster-bearing primary resource once."""
        inputs: list[CanvasResampleResourceInput] = []
        replacements: dict[uuid.UUID, uuid.UUID] = {}
        estimated_bytes = 0
        for layer in layers:
            source = layer.source
            if not isinstance(source, ProjectResourceReference):
                continue
            source_id = source.resource_id
            if source_id in replacements:
                continue
            record = self._document.resources.get(source_id)
            if record is None or record.kind not in _RASTER_KINDS:
                continue
            payload = self._payload(record.kind, source_id)
            target_id = uuid.uuid4()
            replacements[source_id] = target_id
            source_bytes = _payload_bytes(payload)
            estimated_bytes += source_bytes + _scaled_bytes(source_bytes, scale)
            inputs.append(
                CanvasResampleResourceInput(
                    source_id,
                    target_id,
                    record.kind,
                    record.revision,
                    payload,
                )
            )
        return tuple(inputs), replacements, estimated_bytes

    def install(self, item: CanvasResampleResourceProduct) -> None:
        """Install one detached payload under its predetermined identity."""
        if item.kind is ProjectResourceKind.RASTER:
            assert isinstance(item.payload, SparseRasterSnapshot)
            self._document.editable_raster_assets.restore(item.target_id, item.payload)
        elif item.kind in {
            ProjectResourceKind.IMPORTED_RASTER,
            ProjectResourceKind.LINKED_RASTER,
        }:
            assert isinstance(item.payload, QImage)
            self._document.placed_assets.create_embedded(
                item.payload,
                asset_id=item.target_id,
            )
        else:
            assert isinstance(item.payload, CoverageAssetSnapshot)
            self._masks.restore_mask(item.target_id, item.payload)

    def discard(
        self,
        installed: tuple[CanvasResampleResourceProduct, ...],
    ) -> None:
        """Remove products left unreachable by a failed atomic adoption."""
        for item in reversed(installed):
            if item.kind is ProjectResourceKind.RASTER:
                self._document.editable_raster_assets.remove(item.target_id)
            elif item.kind in {
                ProjectResourceKind.IMPORTED_RASTER,
                ProjectResourceKind.LINKED_RASTER,
            }:
                self._document.placed_assets.remove(item.target_id)
            else:
                self._masks.delete_mask(item.target_id)

    def revisions_match(
        self,
        resources: tuple[CanvasResampleResourceInput, ...],
    ) -> bool:
        """Return whether every captured source revision remains current."""
        return all(
            (record := self._document.resources.get(item.source_id)) is not None
            and record.revision == item.revision
            for item in resources
        )

    def _payload(
        self,
        kind: ProjectResourceKind,
        resource_id: uuid.UUID,
    ) -> RasterSourceSnapshot:
        """Capture one authoritative raster-bearing resource payload."""
        if kind is ProjectResourceKind.RASTER:
            asset = self._document.editable_raster_assets.get(resource_id)
            if asset is None:
                raise ValueError("editable raster payload is unavailable")
            return asset.surface.sparse_snapshot()
        if kind in {
            ProjectResourceKind.IMPORTED_RASTER,
            ProjectResourceKind.LINKED_RASTER,
        }:
            placed = self._document.placed_assets.get(resource_id)
            if placed is None or placed.image is None or placed.image.isNull():
                raise ValueError("placed raster pixels are unavailable")
            return placed
        layer = self._masks.get_layer(resource_id)
        if layer is None:
            raise ValueError("coverage payload is unavailable")
        return layer.coverage.state_snapshot()


_RASTER_KINDS = frozenset(
    {
        ProjectResourceKind.RASTER,
        ProjectResourceKind.IMPORTED_RASTER,
        ProjectResourceKind.LINKED_RASTER,
        ProjectResourceKind.COVERAGE,
    }
)


def _payload_bytes(payload: RasterSourceSnapshot) -> int:
    """Return a conservative logical byte estimate for execution admission."""
    if isinstance(payload, SparseRasterSnapshot):
        return payload.bounds.width * payload.bounds.height * payload.channels
    if isinstance(payload, PlacedAssetSnapshot):
        return payload.source_size.width() * payload.source_size.height() * 4
    bounds = payload.raster.bounds
    return 0 if bounds is None else bounds.width * bounds.height


def _scaled_bytes(source_bytes: int, scale: LayerTransform) -> int:
    """Estimate detached output bytes from the requested area scale."""
    return max(1, round(source_bytes * abs(scale.m11 * scale.m22)))


__all__ = ["CanvasResampleResourceOwner"]
