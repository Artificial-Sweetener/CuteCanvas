#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Composition references for editable color-raster sources."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EditableRasterReference:
    """Identify one reusable editable premultiplied-RGBA asset."""

    raster_id: uuid.UUID

    @property
    def kind(self) -> str:
        """Return the stable editable-raster source kind."""
        return "raster"

    @property
    def resource_id(self) -> uuid.UUID:
        """Return the referenced editable-raster identity."""
        return self.raster_id
