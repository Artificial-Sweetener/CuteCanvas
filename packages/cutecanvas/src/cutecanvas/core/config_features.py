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
"""CuteCanvas-owned authoring configuration namespaces."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from qpane.sdk.configuration import (
    ConfigFeatureRegistry,
    FeatureConfigDescriptor,
    require_feature_slice,
)
from qpane.sdk.configuration import iter_descriptors as iter_qpane_descriptors

from .config import Config

_BASE_CONFIG = Config()


@dataclass
class BrushConfigSlice:
    """Brush authoring and pressure-response settings."""

    default_brush_size: int = _BASE_CONFIG.default_brush_size
    brush_scroll_increment: int = _BASE_CONFIG.brush_scroll_increment
    touch_paint_enabled: bool = _BASE_CONFIG.touch_paint_enabled
    stylus_paint_enabled: bool = _BASE_CONFIG.stylus_paint_enabled
    pen_pressure_enabled: bool = _BASE_CONFIG.pen_pressure_enabled
    pen_pressure_min_ratio: float = _BASE_CONFIG.pen_pressure_min_ratio
    pen_pressure_gamma: float = _BASE_CONFIG.pen_pressure_gamma


@dataclass
class MaskConfigSlice:
    """Mask editing, autosave, and diagnostics settings."""

    mask_undo_limit: int = _BASE_CONFIG.mask_undo_limit
    smart_select_min_size: int = _BASE_CONFIG.smart_select_min_size
    mask_border_enabled: bool = _BASE_CONFIG.mask_border_enabled
    mask_prefetch_enabled: bool = _BASE_CONFIG.mask_prefetch_enabled
    mask_autosave_enabled: bool = _BASE_CONFIG.mask_autosave_enabled
    mask_autosave_on_creation: bool = _BASE_CONFIG.mask_autosave_on_creation
    mask_autosave_debounce_ms: int = _BASE_CONFIG.mask_autosave_debounce_ms
    mask_autosave_path_template: str = _BASE_CONFIG.mask_autosave_path_template


@dataclass
class SamConfigSlice:
    """SAM checkpoint, device, prefetch, and cache settings."""

    sam_device: str = _BASE_CONFIG.sam_device
    sam_model_path: str | None = _BASE_CONFIG.sam_model_path
    sam_model_url: str = _BASE_CONFIG.sam_model_url
    sam_model_hash: str | None = _BASE_CONFIG.sam_model_hash
    sam_download_mode: str = _BASE_CONFIG.sam_download_mode
    sam_prefetch_depth: int | None = _BASE_CONFIG.sam_prefetch_depth
    sam_cache_limit: int = _BASE_CONFIG.sam_cache_limit


def _validate_brush_config(settings: BrushConfigSlice) -> None:
    """Validate brush geometry and input policy."""
    if settings.default_brush_size <= 0:
        raise ValueError("default_brush_size must be greater than 0")
    if settings.brush_scroll_increment <= 0:
        raise ValueError("brush_scroll_increment must be greater than 0")
    for field_name in (
        "touch_paint_enabled",
        "stylus_paint_enabled",
        "pen_pressure_enabled",
    ):
        if not isinstance(getattr(settings, field_name), bool):
            raise TypeError(f"{field_name} must be a boolean")
    if not 0 < settings.pen_pressure_min_ratio <= 1:
        raise ValueError("pen_pressure_min_ratio must be greater than 0 and at most 1")
    if settings.pen_pressure_gamma <= 0:
        raise ValueError("pen_pressure_gamma must be greater than 0")


def _validate_mask_config(settings: MaskConfigSlice) -> None:
    """Validate mask history and autosave policy."""
    if settings.mask_undo_limit < 0:
        raise ValueError("mask_undo_limit must be non-negative")
    if settings.smart_select_min_size <= 0:
        raise ValueError("smart_select_min_size must be greater than 0")
    if settings.mask_autosave_debounce_ms < 0:
        raise ValueError("mask_autosave_debounce_ms must be non-negative")
    if settings.mask_autosave_enabled and not settings.mask_autosave_path_template:
        raise ValueError(
            "mask_autosave_path_template must be set when autosave is enabled"
        )


def _validate_sam_config(settings: SamConfigSlice) -> None:
    """Validate SAM resources and host device availability."""
    if str(settings.sam_download_mode).strip().lower() not in {
        "blocking",
        "background",
        "disabled",
    }:
        raise ValueError(
            "sam_download_mode must be one of: blocking, background, disabled"
        )
    _validate_optional_path(settings.sam_model_path)
    if (
        not isinstance(settings.sam_model_url, str)
        or not settings.sam_model_url.strip()
    ):
        raise ValueError("sam_model_url must be a non-empty string")
    if settings.sam_model_hash is not None and (
        not isinstance(settings.sam_model_hash, str)
        or not settings.sam_model_hash.strip()
    ):
        raise ValueError("sam_model_hash must be a non-empty string when set")
    if settings.sam_prefetch_depth is not None and settings.sam_prefetch_depth < 0:
        raise ValueError("sam_prefetch_depth must be non-negative or None")
    if settings.sam_cache_limit < 0:
        raise ValueError("sam_cache_limit must be non-negative")
    _validate_sam_device_available(settings.sam_device)


def _validate_optional_path(value: object) -> None:
    """Validate an optional filesystem path value."""
    if value is None:
        return
    normalized = os.fspath(value) if isinstance(value, os.PathLike) else value
    if not isinstance(normalized, str) or not normalized.strip():
        raise ValueError("sam_model_path must be a non-empty string when set")


def _import_torch():
    """Import torch only when a non-CPU device needs validation."""
    import importlib

    return importlib.import_module("torch")


def _validate_sam_device_available(device: str) -> None:
    """Validate that the requested SAM device exists on this host."""
    normalized = str(device or "").strip().lower()
    if normalized == "cpu":
        return
    if not normalized:
        raise ValueError("sam_device must be specified")
    try:
        torch = _import_torch()
    except Exception as exc:
        raise ValueError(
            f"SAM device '{device}' requested but torch is unavailable"
        ) from exc
    if normalized.startswith("cuda"):
        cuda = getattr(torch, "cuda", None)
        if cuda is None or not callable(getattr(cuda, "is_available", None)):
            raise ValueError("torch.cuda is unavailable; cannot use CUDA device")
        if not cuda.is_available():
            raise ValueError("CUDA device requested but torch reports no CUDA devices")
        return
    if normalized == "mps":
        mps = getattr(torch, "mps", None)
        if mps is None or not callable(getattr(mps, "is_available", None)):
            raise ValueError("torch.mps is unavailable; cannot use MPS device")
        if not mps.is_available():
            raise ValueError("MPS device requested but torch reports no MPS devices")
        return
    raise ValueError(f"Unknown SAM device '{device}'")


BRUSH_DESCRIPTOR = FeatureConfigDescriptor(
    namespace="brush",
    schema=BrushConfigSlice,
    title="Brush input",
    description="Brush sizing and pressure response.",
    validators=(_validate_brush_config,),
)
MASK_DESCRIPTOR = FeatureConfigDescriptor(
    namespace="mask",
    schema=MaskConfigSlice,
    requires=("mask",),
    title="Masks",
    description="Mask editing, autosave, and diagnostics.",
    validators=(_validate_mask_config,),
)
SAM_DESCRIPTOR = FeatureConfigDescriptor(
    namespace="sam",
    schema=SamConfigSlice,
    requires=("sam",),
    title="SAM",
    description="Smart selection model and predictor policy.",
    validators=(_validate_sam_config,),
)

_REGISTRY = ConfigFeatureRegistry()
for _descriptor in (
    *iter_qpane_descriptors(),
    BRUSH_DESCRIPTOR,
    MASK_DESCRIPTOR,
    SAM_DESCRIPTOR,
):
    _REGISTRY.register(_descriptor)


def iter_descriptors() -> tuple[FeatureConfigDescriptor, ...]:
    """Return QPane and CuteCanvas descriptors in ownership order."""
    return _REGISTRY.values()


def descriptors_by_namespace() -> Mapping[str, FeatureConfigDescriptor]:
    """Return all CuteCanvas-visible descriptors by namespace."""
    return _REGISTRY.as_mapping()


def require_mask_config(source: object) -> MaskConfigSlice:
    """Resolve the installed mask configuration slice."""
    return require_feature_slice("mask", MaskConfigSlice, source)


def require_sam_config(source: object) -> SamConfigSlice:
    """Resolve the installed SAM configuration slice."""
    return require_feature_slice("sam", SamConfigSlice, source)
