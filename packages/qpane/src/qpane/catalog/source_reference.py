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
"""Composition references for catalog-owned image sources."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CatalogImageReference:
    """Identify one catalog image independently of any layer instance."""

    image_id: uuid.UUID

    @property
    def kind(self) -> str:
        """Return the stable catalog source kind."""
        return "catalog-image"

    @property
    def resource_id(self) -> uuid.UUID:
        """Return the referenced catalog image identity."""
        return self.image_id
