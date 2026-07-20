#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Stable source-reference contracts shared by composition collaborators."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@runtime_checkable
class LayerSourceReference(Protocol):
    """Identify one reusable source without carrying revision or presentation."""

    @property
    def kind(self) -> str:
        """Return the stable persistence and routing kind."""
        ...

    @property
    def resource_id(self) -> uuid.UUID:
        """Return the durable source identity shared by layer instances."""
        ...


@dataclass(frozen=True, slots=True)
class PlaceholderImageReference:
    """Identify one internal placeholder image source."""

    source_id: uuid.UUID

    @property
    def kind(self) -> str:
        """Return the stable placeholder source kind."""
        return "placeholder-image"

    @property
    def resource_id(self) -> uuid.UUID:
        """Return the placeholder source identity."""
        return self.source_id
