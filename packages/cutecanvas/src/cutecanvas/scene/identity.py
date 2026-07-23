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
"""Deterministic identities for editor-owned layer resources."""

from __future__ import annotations

import uuid

_MASK_LAYER_NAMESPACE = uuid.UUID("80ae57c6-cf1c-5e9a-971f-5161839f0c7f")
_EDITABLE_RASTER_LAYER_NAMESPACE = uuid.UUID("31c5ff47-caef-51c4-8f30-f4f79d2c6d87")
_VECTOR_LAYER_NAMESPACE = uuid.UUID("fc7986d7-c0d8-566b-b709-186763a78f97")


def mask_layer_id(scene_id: uuid.UUID, mask_id: uuid.UUID) -> uuid.UUID:
    """Return the deterministic scene-layer ID for a mask source."""
    return uuid.uuid5(_MASK_LAYER_NAMESPACE, f"{scene_id}:{mask_id}")


def editable_raster_layer_id(scene_id: uuid.UUID, raster_id: uuid.UUID) -> uuid.UUID:
    """Return the deterministic scene-layer ID for an editable raster source."""
    return uuid.uuid5(_EDITABLE_RASTER_LAYER_NAMESPACE, f"{scene_id}:{raster_id}")


def vector_layer_id(scene_id: uuid.UUID, vector_id: uuid.UUID) -> uuid.UUID:
    """Return the deterministic scene-layer ID for a vector source."""
    return uuid.uuid5(_VECTOR_LAYER_NAMESPACE, f"{scene_id}:{vector_id}")
