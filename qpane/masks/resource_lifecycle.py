#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Final-release ownership for composition-referenced mask assets."""

from __future__ import annotations

from dataclasses import dataclass

from ..scene.source_references import LayerSourceReference
from .mask import MaskAssetStore
from .source_reference import MaskAssetReference


@dataclass(frozen=True, slots=True)
class MaskResourceLifecycleOwner:
    """Delete mask payloads after their final composition lease is released."""

    assets: MaskAssetStore
    source_type = MaskAssetReference

    def release_unreachable(self, source: LayerSourceReference) -> None:
        """Delete an unreachable mask payload when it is still present."""
        if isinstance(source, MaskAssetReference):
            self.assets.delete_mask(source.mask_id)
