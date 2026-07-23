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

"""Snapshot models mapping CuteCanvas catalog state to dock rows for the example.

Each dataclass mirrors the fields the dock renders: images and masks grouped by
link membership, with selection identifiers carried alongside.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtGui import QColor


@dataclass(slots=True)
class CatalogMask:
    """Presentation data for a mask layer entry."""

    mask_id: uuid.UUID
    label: str
    color: QColor
    is_active: bool


@dataclass(slots=True)
class CatalogImage:
    """Presentation data for an image row within the catalog."""

    image_id: uuid.UUID
    label: str
    index: int
    path: Path | None
    is_current: bool
    link_id: uuid.UUID | None
    masks: list[CatalogMask] = field(default_factory=list)

    @property
    def is_linked(self) -> bool:
        """Return True when this image participates in a link group."""
        return self.link_id is not None


@dataclass(slots=True)
class CatalogGroup:
    """Container for linked and unlinked image collections.

    Extend by adding fields that the dock can render (e.g., tooltips, diagnostics badges).
    """

    group_id: uuid.UUID | None
    title: str
    images: list[CatalogImage] = field(default_factory=list)
    is_link_group: bool = False


@dataclass(slots=True)
class CatalogSnapshot:
    """Aggregate catalog state emitted to the dock for rendering rows and link groups."""

    groups: list[CatalogGroup]
    current_image_id: uuid.UUID | None
    active_mask_id: uuid.UUID | None
    image_count: int
    mask_capable: bool
