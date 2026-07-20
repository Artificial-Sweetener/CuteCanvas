#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""History value for one durable scene-layer affine transform edit."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from .affine import LayerTransform


@dataclass(frozen=True, slots=True)
class LayerTransformEdit:
    """Capture one exact applied scene-layer transform transition."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    before: LayerTransform
    after: LayerTransform

    @property
    def scope_id(self) -> uuid.UUID:
        """Return the scene identity owning this edit."""
        return self.scene_id

    @property
    def retained_bytes(self) -> int:
        """Return the fixed value-storage cost used for history budgeting."""
        return 96
