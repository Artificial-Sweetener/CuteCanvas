#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Composition references for placed linked or embedded raster assets."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PlacedAssetReference:
    """Identify one reusable non-destructive placed asset."""

    asset_id: uuid.UUID

    @property
    def kind(self) -> str:
        """Return the stable placed-asset source kind."""
        return "placed-asset"

    @property
    def resource_id(self) -> uuid.UUID:
        """Return the reusable asset identity."""
        return self.asset_id
