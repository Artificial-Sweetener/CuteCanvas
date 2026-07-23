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
"""Typed reusable source reference for vector documents."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from qpane.sdk.scene import LayerSourceReference


@dataclass(frozen=True, slots=True)
class VectorDocumentReference(LayerSourceReference):
    """Reference one vector document independently of scene instances."""

    vector_id: uuid.UUID

    @property
    def kind(self) -> str:
        """Return the stable source-domain name."""
        return "vector"

    @property
    def resource_id(self) -> uuid.UUID:
        """Return the shared vector document identity."""
        return self.vector_id
