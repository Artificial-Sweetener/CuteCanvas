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
"""QPane-owned viewer and rendering configuration namespaces."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from copy import deepcopy
from dataclasses import dataclass, field

from .config import CacheSettings, Config
from .config_schema import ConfigFeatureRegistry, FeatureConfigDescriptor

_BASE_CONFIG = Config()


def _clone_cache_defaults() -> CacheSettings:
    """Return detached cache defaults."""
    cache = _BASE_CONFIG.cache
    return cache.clone() if isinstance(cache, CacheSettings) else CacheSettings()


@dataclass
class CoreConfigSlice:
    """Settings owned by the viewer, renderer, cache, and scheduler."""

    cache: CacheSettings = field(default_factory=_clone_cache_defaults)
    tile_size: int = _BASE_CONFIG.tile_size
    tile_overlap: int = _BASE_CONFIG.tile_overlap
    min_view_size_px: int = _BASE_CONFIG.min_view_size_px
    canvas_expansion_factor: float = _BASE_CONFIG.canvas_expansion_factor
    safe_min_zoom: float = _BASE_CONFIG.safe_min_zoom
    drag_out_enabled: bool = _BASE_CONFIG.drag_out_enabled
    concurrency: MutableMapping[str, object] = field(
        default_factory=lambda: deepcopy(_BASE_CONFIG.concurrency)
    )


@dataclass
class InputConfigSlice:
    """Pointer navigation and physical input policy."""

    touch_navigation_enabled: bool = _BASE_CONFIG.touch_navigation_enabled
    palm_rejection_ms: int = _BASE_CONFIG.palm_rejection_ms
    touch_inertia_enabled: bool = _BASE_CONFIG.touch_inertia_enabled
    touch_inertia_deceleration: float = _BASE_CONFIG.touch_inertia_deceleration


@dataclass
class DiagnosticsConfigSlice:
    """Viewer diagnostics and renderer visualization settings."""

    diagnostics_overlay_enabled: bool = _BASE_CONFIG.diagnostics_overlay_enabled
    diagnostics_domains_enabled: tuple[str, ...] = tuple(
        _BASE_CONFIG.diagnostics_domains_enabled
    )
    draw_tile_grid: bool = _BASE_CONFIG.draw_tile_grid


def _validate_core_config(settings: CoreConfigSlice) -> None:
    """Validate renderer geometry and cache settings."""
    if settings.tile_size <= 0:
        raise ValueError("tile_size must be greater than 0")
    if settings.tile_overlap < 0 or settings.tile_overlap >= settings.tile_size:
        raise ValueError("tile_overlap must be non-negative and smaller than tile_size")
    if settings.min_view_size_px <= 0:
        raise ValueError("min_view_size_px must be greater than 0")
    if settings.canvas_expansion_factor <= 0:
        raise ValueError("canvas_expansion_factor must be greater than 0")
    if settings.safe_min_zoom <= 0:
        raise ValueError("safe_min_zoom must be greater than 0")


def _validate_input_config(settings: InputConfigSlice) -> None:
    """Validate navigation input policy."""
    if not isinstance(settings.touch_navigation_enabled, bool):
        raise TypeError("touch_navigation_enabled must be a boolean")
    if settings.palm_rejection_ms < 0:
        raise ValueError("palm_rejection_ms must be non-negative")
    if not isinstance(settings.touch_inertia_enabled, bool):
        raise TypeError("touch_inertia_enabled must be a boolean")
    if settings.touch_inertia_deceleration <= 0:
        raise ValueError("touch_inertia_deceleration must be greater than 0")


def _validate_diagnostics_config(settings: DiagnosticsConfigSlice) -> None:
    """Validate diagnostic presentation settings."""
    if not isinstance(settings.diagnostics_overlay_enabled, bool):
        raise TypeError("diagnostics_overlay_enabled must be a boolean")
    if not isinstance(settings.draw_tile_grid, bool):
        raise TypeError("draw_tile_grid must be a boolean")
    if not isinstance(settings.diagnostics_domains_enabled, (tuple, list)):
        raise TypeError("diagnostics_domains_enabled must be a sequence of strings")
    if not all(
        isinstance(domain, str) for domain in settings.diagnostics_domains_enabled
    ):
        raise ValueError("diagnostics_domains_enabled must contain strings only")


CORE_DESCRIPTOR = FeatureConfigDescriptor(
    namespace="core",
    schema=CoreConfigSlice,
    title="Viewer",
    description="Viewport, cache, and concurrency settings.",
    validators=(_validate_core_config,),
)
INPUT_DESCRIPTOR = FeatureConfigDescriptor(
    namespace="input",
    schema=InputConfigSlice,
    title="Navigation input",
    description="Touch, pen, and kinetic viewport navigation policy.",
    validators=(_validate_input_config,),
)
DIAGNOSTICS_DESCRIPTOR = FeatureConfigDescriptor(
    namespace="diagnostics",
    schema=DiagnosticsConfigSlice,
    title="Diagnostics",
    description="Viewer diagnostics and render visualization.",
    validators=(_validate_diagnostics_config,),
)

_REGISTRY = ConfigFeatureRegistry()
for _descriptor in (CORE_DESCRIPTOR, INPUT_DESCRIPTOR, DIAGNOSTICS_DESCRIPTOR):
    _REGISTRY.register(_descriptor)


def iter_descriptors() -> tuple[FeatureConfigDescriptor, ...]:
    """Return QPane-owned descriptors in deterministic order."""
    return _REGISTRY.values()


def descriptors_by_namespace() -> Mapping[str, FeatureConfigDescriptor]:
    """Return QPane-owned descriptors by namespace."""
    return _REGISTRY.as_mapping()
