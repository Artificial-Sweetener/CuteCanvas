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
"""CuteCanvas-owned authoring configuration layered over QPane rendering."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from qpane.sdk.configuration import CacheSettings
from qpane.sdk.configuration import Config as RenderConfig

SAM_DEFAULT_MODEL_URL = (
    "https://github.com/ChaoningZhang/MobileSAM/raw/master/weights/mobile_sam.pt"
)
SAM_DEFAULT_MODEL_HASH = (
    "6dbb90523a35330fedd7f1d3dfc66f995213d81b29a5ca8108dbcdd4e37d6c2f"
)

_EDITOR_DEFAULTS: dict[str, Any] = {
    "default_brush_size": 30,
    "brush_scroll_increment": 5,
    "touch_paint_enabled": True,
    "stylus_paint_enabled": True,
    "pen_pressure_enabled": True,
    "pen_pressure_min_ratio": 0.15,
    "pen_pressure_gamma": 1.0,
    "mask_undo_limit": 20,
    "smart_select_min_size": 5,
    "mask_border_enabled": False,
    "mask_prefetch_enabled": True,
    "mask_autosave_enabled": False,
    "mask_autosave_on_creation": True,
    "mask_autosave_debounce_ms": 2000,
    "mask_autosave_path_template": "./saved_masks/{image_name}-{mask_id}.png",
    "sam_device": "cpu",
    "sam_model_path": None,
    "sam_model_url": SAM_DEFAULT_MODEL_URL,
    "sam_model_hash": None,
    "sam_download_mode": "background",
    "sam_prefetch_depth": None,
    "sam_cache_limit": 1,
}

_EDITOR_CONCURRENCY: dict[str, Any] = {
    "category_priorities": {
        "mask_stroke": 60,
        "mask_snippet": 50,
        "sam": 5,
    },
    "device_limits": {
        "cpu": {"sam": 2},
        "cuda": {"sam": 1},
    },
}


def _combined_concurrency_defaults() -> dict[str, Any]:
    """Merge editor worker categories into QPane's generic scheduler policy."""
    base = deepcopy(RenderConfig.config_defaults()["concurrency"])
    for field, overrides in _EDITOR_CONCURRENCY.items():
        current = base.setdefault(field, {})
        current.update(deepcopy(overrides))
    return base


def _editor_cache_defaults() -> CacheSettings:
    """Return QPane cache policy extended with editor-owned consumers."""
    cache = CacheSettings()
    cache.weights.extensions.update({"mask_overlays": 50.0, "models": 10.0})
    cache.overrides_mb.update({"mask_overlays": None, "models": None})
    cache.prefetch.extensions.update({"scene_sources": -1, "source_warmup": 0})
    return cache


class Config(RenderConfig):
    """Configure CuteCanvas authoring together with inherited QPane rendering."""

    __slots__ = tuple(_EDITOR_DEFAULTS)

    def __init__(self, **overrides: Any) -> None:
        """Initialize independent rendering and authoring defaults."""
        RenderConfig.__init__(self)
        self.cache = _editor_cache_defaults()
        self.concurrency = _combined_concurrency_defaults()
        for key, value in _EDITOR_DEFAULTS.items():
            setattr(self, key, deepcopy(value))
        if overrides:
            self.configure(**overrides)

    @staticmethod
    def feature_descriptors() -> Mapping[str, object]:
        """Expose all rendering and authoring descriptors for editor hosts."""
        from .config_features import descriptors_by_namespace

        return descriptors_by_namespace()

    @classmethod
    def config_defaults(cls) -> Mapping[str, Any]:
        """Return defaults for the combined renderer/editor configuration."""
        defaults = {
            key: deepcopy(value)
            for key, value in RenderConfig.config_defaults().items()
        }
        defaults["concurrency"] = _combined_concurrency_defaults()
        defaults["cache"] = _editor_cache_defaults()
        defaults.update(
            {key: deepcopy(value) for key, value in _EDITOR_DEFAULTS.items()}
        )
        return defaults

    @classmethod
    def config_keys(cls) -> tuple[str, ...]:
        """Return renderer fields followed by editor-owned fields."""
        return (*RenderConfig.config_keys(), *_EDITOR_DEFAULTS)
