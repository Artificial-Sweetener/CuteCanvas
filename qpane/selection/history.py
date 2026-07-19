#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Chronological edit values for composition pixel selections."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from ..coverage import CoverageSnapshot


@dataclass(frozen=True, slots=True)
class PixelSelectionEdit:
    """Capture one applied pixel-selection transition."""

    scene_id: uuid.UUID
    before: CoverageSnapshot | None
    after: CoverageSnapshot | None

    @property
    def scope_id(self) -> uuid.UUID:
        """Return the scene identity owning this edit."""
        return self.scene_id

    @property
    def retained_bytes(self) -> int:
        """Return detached coverage bytes retained by this command."""
        return _snapshot_bytes(self.before) + _snapshot_bytes(self.after)


def _snapshot_bytes(snapshot: CoverageSnapshot | None) -> int:
    """Return pixel storage retained by an optional coverage snapshot."""
    return 0 if snapshot is None else int(snapshot.pixels.nbytes)
