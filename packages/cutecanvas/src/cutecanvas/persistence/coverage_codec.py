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
"""Archive codec for retained hybrid coverage authorship."""

from __future__ import annotations

import uuid
import zipfile
from dataclasses import fields

import numpy as np
from qpane.sdk.scene import LayerTransform, RasterBounds

from ..coverage import (
    CoverageCombineMode,
    CoverageDocument,
    CoverageSnapshot,
    RasterCoverageItem,
    StrokeCoverageItem,
    VectorCoverageItem,
)
from ..painting.model import BrushOperation, BrushStrokeSegment
from ..types import RasterExtentPolicy
from .vector_object_codec import decode_vector_object, encode_vector_object


def write_coverage_pixels(
    container: zipfile.ZipFile,
    resource_id: uuid.UUID,
    document: CoverageDocument,
) -> None:
    """Write retained raster contributions without flattening the document."""
    for item in document.items:
        if not isinstance(item, RasterCoverageItem):
            continue
        path = _raster_item_path(resource_id, item.item_id)
        with container.open(path, "w") as stream:
            np.save(stream, item.coverage.pixels, allow_pickle=False)


def encode_coverage_document(
    resource_id: uuid.UUID,
    document: CoverageDocument,
) -> dict[str, object]:
    """Return one retained coverage document's serializable values."""
    if document.document_id != resource_id:
        raise ValueError("coverage document identity must match its resource")
    items: list[dict[str, object]] = []
    for item in document.items:
        common: dict[str, object] = {
            "item_id": str(item.item_id),
            "combine_mode": item.combine_mode.value,
            "transform": _encode_transform(item.transform),
        }
        if isinstance(item, RasterCoverageItem):
            bounds = item.coverage.bounds
            common.update(
                {
                    "kind": "raster",
                    "bounds": None if bounds is None else _encode_bounds(bounds),
                    "extent_policy": item.coverage.extent_policy.value,
                    "pixels": _raster_item_path(resource_id, item.item_id),
                }
            )
        elif isinstance(item, VectorCoverageItem):
            common.update(
                {
                    "kind": "vector",
                    "geometry": encode_vector_object(item.geometry),
                    "feather_radius": item.feather_radius,
                }
            )
        elif isinstance(item, StrokeCoverageItem):
            common.update(
                {
                    "kind": "stroke",
                    "segments": [_encode_segment(segment) for segment in item.segments],
                }
            )
        else:  # pragma: no cover - closed domain guard
            raise TypeError(f"unsupported coverage item: {type(item)!r}")
        items.append(common)
    return {
        "document_id": str(document.document_id),
        "revision": document.revision,
        "items": items,
    }


def decode_coverage_document(
    container: zipfile.ZipFile,
    resource_id: uuid.UUID,
    value: object,
    *,
    pixel_limit: int,
) -> CoverageDocument:
    """Validate and reconstruct retained coverage without evaluating it."""
    if not isinstance(value, dict):
        raise TypeError("retained coverage must be an object")
    document_id = uuid.UUID(str(value.get("document_id")))
    if document_id != resource_id:
        raise ValueError("coverage document identity must match its resource")
    item_values = value.get("items")
    if not isinstance(item_values, list):
        raise TypeError("retained coverage items must be a list")
    items = tuple(
        _decode_item(container, resource_id, item, pixel_limit=pixel_limit)
        for item in item_values
    )
    return CoverageDocument(
        document_id=document_id,
        items=items,
        revision=int(value.get("revision", 0)),
    )


def _decode_item(
    container: zipfile.ZipFile,
    resource_id: uuid.UUID,
    value: object,
    *,
    pixel_limit: int,
) -> RasterCoverageItem | VectorCoverageItem | StrokeCoverageItem:
    """Decode one typed retained contribution."""
    if not isinstance(value, dict):
        raise TypeError("retained coverage entries must be objects")
    item_id = uuid.UUID(str(value.get("item_id")))
    combine = CoverageCombineMode(str(value.get("combine_mode")))
    transform = _decode_transform(value.get("transform"))
    kind = str(value.get("kind"))
    if kind == "raster":
        bounds_value = value.get("bounds")
        bounds = None if bounds_value is None else _decode_bounds(bounds_value)
        expected_path = _raster_item_path(resource_id, item_id)
        if value.get("pixels") != expected_path:
            raise ValueError("coverage raster path does not match its identity")
        info = container.getinfo(expected_path)
        if info.file_size > pixel_limit + 4096:
            raise ValueError("coverage raster payload exceeds archive size limit")
        with container.open(expected_path) as stream:
            pixels = np.load(stream, allow_pickle=False)
        return RasterCoverageItem(
            item_id,
            CoverageSnapshot(
                bounds,
                RasterExtentPolicy(str(value.get("extent_policy"))),
                pixels,
            ),
            combine,
            transform,
        )
    if kind == "vector":
        geometry, _point_count = decode_vector_object(value.get("geometry"))
        return VectorCoverageItem(
            item_id,
            geometry,
            combine,
            transform,
            float(value.get("feather_radius", 0.0)),
        )
    if kind == "stroke":
        segment_values = value.get("segments")
        if not isinstance(segment_values, list):
            raise TypeError("coverage stroke segments must be a list")
        return StrokeCoverageItem(
            item_id,
            tuple(_decode_segment(segment) for segment in segment_values),
            combine,
            transform,
        )
    raise ValueError(f"unsupported retained coverage kind: {kind}")


def _encode_segment(segment: BrushStrokeSegment) -> dict[str, object]:
    """Return deterministic brush segment values without derived dabs."""
    result: dict[str, object] = {}
    for definition in fields(BrushStrokeSegment):
        if definition.metadata.get("persist") is False:
            continue
        value = getattr(segment, definition.name)
        if isinstance(value, BrushOperation):
            result[definition.name] = value.value
        elif isinstance(value, LayerTransform):
            result[definition.name] = _encode_transform(value)
        elif isinstance(value, tuple):
            result[definition.name] = list(value)
        else:
            result[definition.name] = value
    return result


def _decode_segment(value: object) -> BrushStrokeSegment:
    """Validate one deterministic brush segment through its domain constructor."""
    if not isinstance(value, dict):
        raise TypeError("coverage stroke segments must be objects")
    allowed = {
        definition.name
        for definition in fields(BrushStrokeSegment)
        if definition.metadata.get("persist") is not False
    }
    supplied = set(value)
    if supplied not in (allowed, allowed - {"tip_transform"}):
        raise ValueError("coverage stroke fields do not match the current format")
    decoded = dict(value)
    decoded["start"] = tuple(float(item) for item in decoded["start"])
    decoded["end"] = tuple(float(item) for item in decoded["end"])
    decoded["operation"] = BrushOperation(str(decoded["operation"]))
    if "tip_transform" in decoded:
        decoded["tip_transform"] = _decode_transform(decoded["tip_transform"])
    return BrushStrokeSegment(**decoded)


def _encode_transform(transform: LayerTransform) -> list[float]:
    """Return six affine coefficients in stable order."""
    return [
        transform.m11,
        transform.m12,
        transform.m21,
        transform.m22,
        transform.dx,
        transform.dy,
    ]


def _decode_transform(value: object) -> LayerTransform:
    """Validate and reconstruct one affine transform."""
    if not isinstance(value, list) or len(value) != 6:
        raise ValueError("coverage transforms must contain six values")
    return LayerTransform(*(float(item) for item in value))


def _encode_bounds(bounds: RasterBounds) -> list[int]:
    """Return integer raster bounds in stable order."""
    return [bounds.x, bounds.y, bounds.width, bounds.height]


def _decode_bounds(value: object) -> RasterBounds:
    """Validate and reconstruct integer raster bounds."""
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError("coverage bounds must contain four integers")
    return RasterBounds(*(int(item) for item in value))


def _raster_item_path(resource_id: uuid.UUID, item_id: uuid.UUID) -> str:
    """Return the collision-free payload path for one retained raster item."""
    return f"masks/{resource_id}/coverage/{item_id}.npy"
