#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Typed reusable source reference for vector documents."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from ..scene.source_references import LayerSourceReference


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
