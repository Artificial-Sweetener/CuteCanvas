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

"""Configuration dataclasses and the mutable Config facade for QPane.

Expose cache and prefetch settings plus the :class:`Config` snapshot wrapper.

Clone configurations before mutating so panes keep isolated cache budgets and
prefetch radii.
"""

from __future__ import annotations

import logging
from collections.abc import (
    Collection,
    Iterable,
    Iterator,
    Mapping,
    MutableMapping,
    Sequence,
)
from copy import deepcopy
from dataclasses import dataclass, field, fields
from typing import (
    Any,
    Literal,
    TypeAlias,
    TypeVar,
)

from typing_extensions import Self

from ..features import FeatureInstallError
from ..ferrastra.reconstruction import RasterReconstructionSpace
from ..types import CacheMode, PlaceholderScaleMode, ZoomMode
from .config_values import normalize_domain_sequence, normalize_enum_value

logger = logging.getLogger(__name__)

TileSizeSetting: TypeAlias = int | Literal["auto"]

_PSUTIL_WARNING_EMITTED = False


def _warn_psutil_missing() -> None:
    """Log once when psutil is unavailable so Auto mode can fall back cleanly."""
    global _PSUTIL_WARNING_EMITTED
    if _PSUTIL_WARNING_EMITTED:
        return
    logger.warning(
        "psutil unavailable; falling back to hard cache cap (1024 MB) in auto mode"
    )
    _PSUTIL_WARNING_EMITTED = True


_AUTO_BUDGET_WARNING_EMITTED = False

_HARD_HEADROOM_WARNING_EMITTED = False


@dataclass
class CacheWeights:
    """Relative weights that apportion the active cache budget."""

    tiles: float = 55.0
    pyramids: float = 45.0
    extensions: MutableMapping[str, float] = field(default_factory=dict)

    def normalized(self, active: Iterable[str] | None = None) -> dict[str, float]:
        """Return normalized weights limited to ``active`` when provided."""
        weights = {
            "tiles": max(0.0, float(self.tiles)),
            "pyramids": max(0.0, float(self.pyramids)),
        }
        weights.update(
            {key: max(0.0, float(value)) for key, value in self.extensions.items()}
        )
        if active is not None:
            weights = {key: value for key, value in weights.items() if key in active}
        total = sum(weights.values())
        if total <= 0:
            count = len(weights) if weights else 0
            if count == 0:
                return {}
            return {key: 1.0 / count for key in weights}
        return {key: value / total for key, value in weights.items()}


@dataclass
class PrefetchSettings:
    """Controls neighbor depths for background prefetch operations."""

    pyramids: int = 2
    tiles: int = 2
    tiles_per_neighbor: int = 4
    extensions: MutableMapping[str, int] = field(default_factory=dict)

    def clone(self) -> PrefetchSettings:
        """Return a defensive copy of the prefetch settings."""
        return PrefetchSettings(
            pyramids=int(self.pyramids),
            tiles=int(self.tiles),
            tiles_per_neighbor=int(self.tiles_per_neighbor),
            extensions={key: int(value) for key, value in self.extensions.items()},
        )

    def apply_mapping(self, mapping: Mapping[str, Any]) -> None:
        """Merge supported keys from ``mapping`` into this configuration.

        Args:
            mapping: Source values that may contain any ``PrefetchSettings``
                attribute. Unsupported keys are ignored.
        """
        for key, value in mapping.items():
            if key in {"pyramids", "tiles", "tiles_per_neighbor"}:
                setattr(self, key, self._coerce_int(value, getattr(self, key)))
            elif key == "extensions":
                if not isinstance(value, Mapping):
                    raise TypeError("cache.prefetch.extensions must be a mapping")
                self.extensions = {
                    str(name): self._coerce_int(depth, -1)
                    for name, depth in value.items()
                }

    def to_dict(self) -> dict[str, int]:
        """Expose the settings as a primitive dictionary."""
        return {
            "pyramids": int(self.pyramids),
            "tiles": int(self.tiles),
            "tiles_per_neighbor": int(self.tiles_per_neighbor),
            "extensions": dict(self.extensions),
        }

    @staticmethod
    def _coerce_int(value: Any, default: int) -> int:
        """Coerce ``value`` to an int, returning ``default`` when conversion fails."""
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(default)


@dataclass
class CacheSettings:
    """Cache budget configuration supporting Auto and Hard modes."""

    mode: str = "auto"
    headroom_percent: float = 0.1
    headroom_cap_mb: int = 4096
    budget_mb: int | None = None
    weights: CacheWeights = field(default_factory=CacheWeights)
    overrides_mb: MutableMapping[str, int | None] = field(
        default_factory=lambda: {
            "tiles": None,
            "pyramids": None,
        }
    )
    prefetch: PrefetchSettings = field(default_factory=PrefetchSettings)

    def clone(self) -> CacheSettings:
        """Return a deep copy so callers can mutate the duplicate safely."""
        return CacheSettings(
            mode=str(self.mode),
            headroom_percent=float(self.headroom_percent),
            headroom_cap_mb=int(self.headroom_cap_mb),
            budget_mb=None if self.budget_mb is None else int(self.budget_mb),
            weights=CacheWeights(
                tiles=self.weights.tiles,
                pyramids=self.weights.pyramids,
                extensions=dict(self.weights.extensions),
            ),
            overrides_mb=dict(self.overrides_mb),
            prefetch=self.prefetch.clone(),
        )

    def resolve_active_budget_bytes(self, psutil_module: Any | None = None) -> int:
        """Return the active budget in bytes based on the configured mode."""
        self._validate_mode_union()
        mode = str(self.mode).lower()
        if mode == "hard":
            budget = 1024 if self.budget_mb is None else int(self.budget_mb)
            return max(0, budget * 1024 * 1024)
        psutil = psutil_module
        if psutil is None:
            try:
                import psutil  # type: ignore
            except ImportError:  # pragma: no cover - optional dependency
                _warn_psutil_missing()
                return 1024 * 1024 * 1024
        try:
            mem = psutil.virtual_memory()
            available = int(mem.available)
            total = int(mem.total)
        except Exception:  # noqa: BLE001 - psutil is an optional system boundary
            logger.warning(
                "Failed to read system memory; falling back to hard cache cap (1024 MB)"
            )
            return 1024 * 1024 * 1024
        headroom_bytes = min(
            int(total * max(0.0, float(self.headroom_percent))),
            max(0, int(self.headroom_cap_mb)) * 1024 * 1024,
        )
        return max(0, available - headroom_bytes)

    def resolve_consumer_budgets_bytes(
        self,
        active_budget_bytes: int,
        *,
        active_consumers: Iterable[str] | None = None,
    ) -> dict[str, int]:
        """Distribute ``active_budget_bytes`` across consumers using weights."""
        active_set = set(active_consumers or ())
        if not active_set:
            active_set = {"tiles", "pyramids"}
        normalized = self.weights.normalized(active_set)
        resolved: dict[str, int] = {}
        budget = max(0, int(active_budget_bytes))
        for key in active_set:
            portion = normalized.get(key, 0.0)
            resolved[key] = int(budget * portion)
        return resolved

    def resolved_consumer_budgets_bytes(
        self,
        *,
        psutil_module: Any | None = None,
        active_consumers: Iterable[str] | None = None,
    ) -> dict[str, int]:
        """Return per-consumer budgets with overrides applied."""
        active_budget_bytes = self.resolve_active_budget_bytes(
            psutil_module=psutil_module
        )
        budgets_bytes = self.resolve_consumer_budgets_bytes(
            active_budget_bytes,
            active_consumers=active_consumers,
        )
        for key, override in self.explicit_overrides_mb().items():
            budgets_bytes[key] = max(0, int(override)) * 1024 * 1024
        return budgets_bytes

    def override_mb(self, cache_name: str) -> int | None:
        """Return the sanitized override for ``cache_name`` or ``None`` when unset."""
        raw = self.overrides_mb.get(cache_name)
        if raw is None:
            return None
        try:
            numeric = int(raw)
        except (TypeError, ValueError):
            return None
        if numeric < 0:
            return None
        return numeric

    def set_override_mb(self, cache_name: str, value: int | None) -> None:
        """Persist an override for ``cache_name`` while sanitizing ``value``."""
        if value is None:
            self.overrides_mb[cache_name] = None
            return
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            self.overrides_mb[cache_name] = None
            return
        if numeric < 0:
            self.overrides_mb[cache_name] = None
        else:
            self.overrides_mb[cache_name] = max(0, numeric)

    def apply_mapping(self, mapping: Mapping[str, Any]) -> None:
        """Merge overrides from ``mapping`` into this cache configuration."""
        forbidden = {"total_mb", "ratios"}
        allowed = {
            "mode",
            "headroom_percent",
            "headroom_cap_mb",
            "budget_mb",
            "weights",
            "prefetch",
            "tiles",
            "pyramids",
            "extensions",
        }
        for key in mapping:
            if key in forbidden:
                raise ValueError(f"cache.{key} is no longer supported")
            if key not in allowed:
                raise ValueError(f"cache.{key} is not supported")
        mode = mapping.get("mode", self.mode)
        self.mode = normalize_enum_value(mode, CacheMode, field="cache mode")
        normalized_mode = self.mode
        global _AUTO_BUDGET_WARNING_EMITTED, _HARD_HEADROOM_WARNING_EMITTED
        for key, value in mapping.items():
            if key == "mode":
                continue
            if key == "headroom_percent":
                if normalized_mode == "hard":
                    if value is None:
                        continue
                    if not _HARD_HEADROOM_WARNING_EMITTED:
                        logger.warning("Ignoring headroom setting in hard cache mode")
                        _HARD_HEADROOM_WARNING_EMITTED = True
                    continue
                self.headroom_percent = float(value)
            elif key == "headroom_cap_mb":
                if normalized_mode == "hard":
                    if value is None:
                        continue
                    if not _HARD_HEADROOM_WARNING_EMITTED:
                        logger.warning("Ignoring headroom setting in hard cache mode")
                        _HARD_HEADROOM_WARNING_EMITTED = True
                    continue
                self.headroom_cap_mb = max(0, int(value))
            elif key == "budget_mb":
                if normalized_mode == "auto":
                    if value is None:
                        continue
                    if not _AUTO_BUDGET_WARNING_EMITTED:
                        logger.warning(
                            "Ignoring budget_mb in auto cache mode; switch to hard "
                            "mode to apply a fixed budget"
                        )
                        _AUTO_BUDGET_WARNING_EMITTED = True
                    continue
                self.budget_mb = None if value is None else max(0, int(value))
            elif key == "weights":
                self._apply_weights(value)
            elif key in {"tiles", "pyramids"}:
                self._apply_cache_bucket(key, value)
            elif key == "extensions":
                self._apply_extensions(value)
            elif key == "prefetch":
                self._apply_prefetch(value)
        self._validate_mode_union()

    def _apply_weights(self, value: Any) -> None:
        """Update the weight struct from mappings or :class:`CacheWeights` instances."""
        if isinstance(value, Mapping):
            for key in ("tiles", "pyramids"):
                if key in value:
                    setattr(self.weights, key, float(value[key]))
            extensions = value.get("extensions")
            if extensions is not None:
                if not isinstance(extensions, Mapping):
                    raise TypeError("cache.weights.extensions must be a mapping")
                self.weights.extensions = {
                    str(key): float(weight) for key, weight in extensions.items()
                }
        elif isinstance(value, CacheWeights):
            self.weights = CacheWeights(
                tiles=value.tiles,
                pyramids=value.pyramids,
                extensions=dict(value.extensions),
            )
        else:
            raise TypeError("cache.weights must be a mapping or CacheWeights instance")

    def _apply_cache_bucket(self, bucket: str, value: Any) -> None:
        """Apply overrides to a single cache bucket (tiles/pyramids/etc.)."""
        if isinstance(value, Mapping):
            if "mb" in value:
                self.set_override_mb(bucket, value["mb"])
        elif value is None:
            self.set_override_mb(bucket, None)
        else:
            self.set_override_mb(bucket, value)

    def _apply_prefetch(self, value: Any) -> None:
        """Update the nested :class:`PrefetchSettings` using supported types."""
        if isinstance(value, PrefetchSettings):
            self.prefetch = value.clone()
        elif isinstance(value, Mapping):
            self.prefetch.apply_mapping(value)
        else:
            raise TypeError("cache.prefetch must be a mapping or PrefetchSettings")

    def _apply_extensions(self, value: Any) -> None:
        """Apply generic extension cache overrides by consumer identifier."""
        if not isinstance(value, Mapping):
            raise TypeError("cache.extensions must be a mapping")
        for consumer_id, override in value.items():
            self._apply_cache_bucket(str(consumer_id), override)

    def to_dict(self) -> dict[str, Any]:
        """Expose the cache settings as a mapping suitable for serialization."""
        self._validate_mode_union()
        weights = {
            "tiles": self.weights.tiles,
            "pyramids": self.weights.pyramids,
            "extensions": dict(self.weights.extensions),
        }
        overrides = {
            key: (value if value is not None else -1)
            for key, value in self.overrides_mb.items()
        }
        normalized_mode = str(self.mode).lower()
        is_auto = normalized_mode == "auto"
        budget_field = None
        if not is_auto:
            budget_field = self.budget_mb if self.budget_mb is not None else 1024
        return {
            "mode": self.mode,
            "headroom_percent": self.headroom_percent if is_auto else None,
            "headroom_cap_mb": self.headroom_cap_mb if is_auto else None,
            "budget_mb": budget_field,
            "weights": weights,
            "prefetch": self.prefetch.to_dict(),
            "tiles": {"mb": overrides.get("tiles", -1)},
            "pyramids": {"mb": overrides.get("pyramids", -1)},
            "extensions": {
                key: {"mb": value}
                for key, value in overrides.items()
                if key not in {"tiles", "pyramids"}
            },
        }

    def explicit_overrides_mb(self) -> dict[str, int]:
        """Return only the cache buckets that have explicit overrides."""
        explicit: dict[str, int] = {}
        for key in self.overrides_mb:
            override = self.override_mb(key)
            if override is not None:
                explicit[key] = override
        return explicit

    def _validate_mode_union(self) -> None:
        """Ensure the configured mode and fields align with the supported union."""
        normalized_mode = normalize_enum_value(self.mode, CacheMode, field="cache mode")
        self.mode = normalized_mode


@dataclass
class PlaceholderSettings:
    """Configure the placeholder image rendered when the catalog is empty."""

    source: str | None = None
    panzoom_enabled: bool = False
    drag_out_enabled: bool = False
    zoom_mode: str = "fit"
    locked_zoom: float | None = None
    locked_size: tuple[int, int] | None = None
    scale_mode: str = "auto"
    display_size: tuple[int, int] | None = None
    min_display_size: tuple[int, int] | None = None
    max_display_size: tuple[int, int] | None = None
    scale_factor: float = 1.0

    def clone(self) -> PlaceholderSettings:
        """Return a defensive copy of the placeholder settings."""
        return PlaceholderSettings(
            source=self.source,
            panzoom_enabled=bool(self.panzoom_enabled),
            drag_out_enabled=bool(self.drag_out_enabled),
            zoom_mode=self.zoom_mode,
            locked_zoom=self.locked_zoom,
            locked_size=tuple(self.locked_size) if self.locked_size else None,
            scale_mode=self.scale_mode,
            display_size=tuple(self.display_size) if self.display_size else None,
            min_display_size=(
                tuple(self.min_display_size) if self.min_display_size else None
            ),
            max_display_size=(
                tuple(self.max_display_size) if self.max_display_size else None
            ),
            scale_factor=float(self.scale_factor),
        )

    def to_dict(self) -> dict[str, Any]:
        """Expose the placeholder settings as JSON-serializable primitives."""
        return {
            "source": self.source,
            "panzoom_enabled": bool(self.panzoom_enabled),
            "drag_out_enabled": bool(self.drag_out_enabled),
            "zoom_mode": self.zoom_mode,
            "locked_zoom": self.locked_zoom,
            "locked_size": tuple(self.locked_size) if self.locked_size else None,
            "scale_mode": self.scale_mode,
            "display_size": tuple(self.display_size) if self.display_size else None,
            "min_display_size": (
                tuple(self.min_display_size) if self.min_display_size else None
            ),
            "max_display_size": (
                tuple(self.max_display_size) if self.max_display_size else None
            ),
            "scale_factor": float(self.scale_factor),
        }

    def apply_mapping(self, mapping: Mapping[str, Any]) -> None:
        """Merge supported keys from ``mapping`` into this configuration."""
        allowed = {
            "source",
            "panzoom_enabled",
            "drag_out_enabled",
            "zoom_mode",
            "locked_zoom",
            "locked_size",
            "scale_mode",
            "display_size",
            "min_display_size",
            "max_display_size",
            "scale_factor",
        }
        for key in mapping:
            if key not in allowed:
                raise ValueError(f"placeholder.{key} is not supported")
        for key, value in mapping.items():
            if key == "source":
                self.source = str(value) if value is not None else None
            elif key == "panzoom_enabled":
                self.panzoom_enabled = bool(value)
            elif key == "drag_out_enabled":
                self.drag_out_enabled = bool(value)
            elif key == "zoom_mode":
                self.zoom_mode = normalize_enum_value(
                    value, ZoomMode, field="placeholder zoom_mode"
                )
            elif key == "locked_zoom":
                self.locked_zoom = float(value) if value is not None else None
            elif key == "locked_size":
                self.locked_size = self._coerce_size(value)
            elif key == "scale_mode":
                self.scale_mode = normalize_enum_value(
                    value, PlaceholderScaleMode, field="placeholder scale_mode"
                )
            elif key == "display_size":
                self.display_size = self._coerce_size(value)
            elif key == "min_display_size":
                self.min_display_size = self._coerce_size(value)
            elif key == "max_display_size":
                self.max_display_size = self._coerce_size(value)
            elif key == "scale_factor":
                try:
                    self.scale_factor = float(value)
                except (TypeError, ValueError) as exc:
                    raise TypeError(
                        "placeholder.scale_factor must be a real number"
                    ) from exc

    @staticmethod
    def _coerce_size(value: Any) -> tuple[int, int] | None:
        """Return a sanitized size tuple or raise when invalid."""
        if value is None:
            return None
        if isinstance(value, Sequence) and len(value) == 2:
            try:
                width = int(value[0])
                height = int(value[1])
            except (TypeError, ValueError) as exc:
                raise TypeError(
                    "placeholder size values must be convertible to integers"
                ) from exc
            if width <= 0 or height <= 0:
                raise ValueError("placeholder sizes must be positive")
            return (width, height)
        raise TypeError("placeholder sizes must be a (width, height) sequence")


_DEFAULTS: dict[str, Any] = {
    "cache": CacheSettings(),
    "placeholder": PlaceholderSettings(),
    "tile_size": "auto",
    "tile_overlap": 8,
    "min_view_size_px": 128,
    "viewport_reconstruction_space": RasterReconstructionSpace.SRGB_ENCODED,
    "canvas_expansion_factor": 1.4,
    "safe_min_zoom": 1e-3,
    "drag_out_enabled": True,
    "normalize_zoom_on_screen_change": False,
    "normalize_zoom_for_one_to_one": False,
    "smooth_zoom_enabled": True,
    "smooth_zoom_duration_ms": 80,
    "smooth_zoom_burst_duration_ms": 20,
    "smooth_zoom_burst_threshold_ms": 25,
    "smooth_zoom_fallback_fps": 60.0,
    "smooth_zoom_use_display_fps": True,
    "touch_navigation_enabled": True,
    "palm_rejection_ms": 800,
    "touch_inertia_enabled": True,
    "touch_inertia_deceleration": 4500.0,
    "diagnostics_overlay_enabled": False,
    "diagnostics_domains_enabled": (),
    "draw_tile_grid": False,
}

# NOTE: Update slots whenever the _DEFAULTS mapping changes so the instance

# layout remains consistent.


_SLOT_KEYS: tuple[str, ...] = tuple(_DEFAULTS.keys())

_ALLOWED_KEYS: tuple[str, ...] = _SLOT_KEYS

ConfigT = TypeVar("ConfigT", bound="Config")


class Config:
    """Mutable snapshot providing cloning helpers for viewer configuration."""

    __slots__ = _SLOT_KEYS

    def __init__(self, **overrides: Any) -> None:
        """Initialize the config with defaults and optional overrides."""
        for key, value in Config.config_defaults().items():
            setattr(self, key, self._copy_value(value))
        if overrides:
            self.configure(**overrides)

    # Public API ---------------------------------------------------------

    @staticmethod
    def feature_descriptors() -> Mapping[str, object]:
        """Expose feature config descriptors keyed by namespace for UI builders."""
        from .config_features import descriptors_by_namespace

        return descriptors_by_namespace()

    @classmethod
    def config_defaults(cls) -> Mapping[str, Any]:
        """Return the authoritative default values owned by this config type."""
        return _DEFAULTS

    @classmethod
    def config_keys(cls) -> tuple[str, ...]:
        """Return the complete ordered field contract for this config type."""
        return tuple(cls.config_defaults())

    def configure(self, config_obj: object | None = None, **kwargs: Any) -> Self:
        """Mutate this instance with values from another object or keyword args.

        Args:
            config_obj: Optional ``Config``/mapping/namespace to read values from.
            **kwargs: Individual key/value overrides applied after ``config_obj``.

        Raises:
            ValueError: When unknown configuration keys are provided.
            TypeError: When inputs are not mappings or supported config objects.

        Returns:
            ``self`` so callers can chain configuration steps.
        """
        if config_obj is not None:
            self._apply_items(self._iter_source_items(config_obj))
        if kwargs:
            self._apply_items(kwargs.items())
        return self

    def copy(self) -> Self:
        """Return a deep copy of this configuration snapshot."""
        clone = type(self)()
        for key in self.config_keys():
            setattr(clone, key, self._copy_value(getattr(self, key)))
        return clone

    def as_dict(self) -> dict[str, Any]:
        """Expose the configuration as JSON-serializable primitives."""
        data = {key: self._copy_value(getattr(self, key)) for key in self.config_keys()}
        cache_settings = getattr(self, "cache", CacheSettings())
        data["cache"] = cache_settings.to_dict()
        placeholder_settings = getattr(self, "placeholder", PlaceholderSettings())
        data["placeholder"] = placeholder_settings.to_dict()
        reconstruction_space = getattr(
            self,
            "viewport_reconstruction_space",
            RasterReconstructionSpace.SRGB_ENCODED,
        )
        data["viewport_reconstruction_space"] = reconstruction_space.value
        return data

    # Internal helpers ---------------------------------------------------

    def _apply_items(self, items: Iterable[tuple[str, Any]]) -> None:
        """Apply key/value overrides while validating supported inputs."""
        for key, value in items:
            if key not in self.config_keys():
                raise ValueError(f"Unknown configuration key: {key}")
            if key == "cache":
                setattr(self, key, self._merge_cache_settings(value))
            elif key == "placeholder":
                setattr(self, key, self._merge_placeholder_settings(value))
            elif key == "diagnostics_domains_enabled":
                setattr(self, key, normalize_domain_sequence(value))
            elif key == "viewport_reconstruction_space":
                canonical = normalize_enum_value(
                    value,
                    RasterReconstructionSpace,
                    field="viewport_reconstruction_space",
                )
                setattr(self, key, RasterReconstructionSpace(canonical))
            else:
                setattr(self, key, self._copy_value(value))

    @staticmethod
    def _iter_source_items(source: object) -> Iterator[tuple[str, Any]]:
        """Yield ``(key, value)`` pairs from supported configuration sources."""
        if isinstance(source, Config):
            for key in source.config_keys():
                yield key, Config._copy_value(getattr(source, key))
            return
        if isinstance(source, Mapping):
            yield from source.items()  # type: ignore[return-value]
            return
        dictionary = getattr(source, "__dict__", None)
        if dictionary is not None:
            yield from dictionary.items()
            return
        raise TypeError(f"Unsupported config source type: {type(source)!r}")

    def _merge_cache_settings(self, overrides: Any) -> CacheSettings:
        """Clone the existing cache settings and merge host overrides safely.

        Raises:
            TypeError: If ``overrides`` is neither a mapping nor a CacheSettings instance.
        """
        current = getattr(self, "cache", None)
        if isinstance(current, CacheSettings):
            cache = current.clone()
        else:
            cache = CacheSettings()
        if overrides is None:
            return cache
        if isinstance(overrides, CacheSettings):
            return overrides.clone()
        if not isinstance(overrides, Mapping):
            raise TypeError(
                "Config 'cache' overrides must be a mapping or CacheSettings"
            )
        cache.apply_mapping(overrides)
        return cache

    def _merge_placeholder_settings(self, overrides: Any) -> PlaceholderSettings:
        """Clone the existing placeholder settings and merge host overrides.

        Raises:
            TypeError: If ``overrides`` is neither a mapping nor a PlaceholderSettings instance.
        """
        current = getattr(self, "placeholder", None)
        if isinstance(current, PlaceholderSettings):
            placeholder = current.clone()
        else:
            placeholder = PlaceholderSettings()
        if overrides is None:
            return placeholder
        if isinstance(overrides, PlaceholderSettings):
            return overrides.clone()
        if not isinstance(overrides, Mapping):
            raise TypeError(
                "Config 'placeholder' overrides must be a mapping or PlaceholderSettings"
            )
        placeholder.apply_mapping(overrides)
        return placeholder

    @staticmethod
    def _copy_value(value: Any) -> Any:
        """Return a defensive copy for mutable default values."""
        return deepcopy(value)


class FeatureAwareConfig:
    """Read-only view exposing feature-specific configuration slices."""

    def __init__(
        self,
        base: Config,
        *,
        descriptors: Sequence[object] | None = None,
        installed_features: Sequence[str] | None = None,
        override_fields: Collection[str] | None = None,
        strict: bool = False,
    ) -> None:
        """Compose feature slices over a base config while tracking inactive overrides."""
        self._base = base
        self._descriptors = tuple(descriptors or ())
        self._installed_features = tuple(installed_features or ())
        self._override_fields = set(override_fields or ())
        self._strict = strict
        self._descriptor_map: dict[str, object] = {}
        self._field_map: dict[str, object] = {}
        self._active_namespaces: set[str] = set()
        self._inactive_fields: dict[str, tuple[str, ...]] = {}
        self._unused_fields: dict[str, tuple[str, ...]] = {}
        self._feature_slices: dict[str, object] = {}
        self._validation_failures: dict[str, str] = {}
        self._build_descriptor_mappings()
        if self._strict and self._unused_fields:
            self._raise_strict_error()

    def for_feature(self, namespace: str) -> object:
        """Return the structured slice for ``namespace`` when installed."""
        descriptor = self._descriptor_map.get(namespace)
        if descriptor is None:
            raise AttributeError(f"Unknown config namespace '{namespace}'")
        if namespace not in self._active_namespaces:
            raise FeatureInstallError(
                f"Feature '{namespace}' is not installed so its configuration is unavailable."
            )
        return self._feature_slices[namespace]

    def inactive_fields(self) -> dict[str, tuple[str, ...]]:
        """Return namespaces and fields that were provided without active features."""
        return dict(self._inactive_fields)

    def unused_fields(self) -> dict[str, tuple[str, ...]]:
        """Return overridden fields ignored because their features are inactive."""
        return {key: tuple(values) for key, values in self._unused_fields.items()}

    def validation_failures(self) -> dict[str, str]:
        """Return validation errors keyed by feature namespace."""
        return dict(self._validation_failures)

    def __getattr__(self, name: str) -> Any:
        """Resolve attributes to active feature slices or fall back to the base config."""
        base_has_attr = hasattr(self._base, name)
        if name in self._field_map:
            descriptor = self._field_map[name]
            namespace = getattr(descriptor, "namespace", "")
            if namespace not in self._active_namespaces:
                raise FeatureInstallError(
                    f"Feature '{namespace}' is not installed so '{name}' is unavailable"
                )
            if namespace in self._feature_slices:
                return getattr(self._feature_slices[namespace], name)
        if base_has_attr:
            return getattr(self._base, name)
        raise AttributeError(name)

    def _build_descriptor_mappings(self) -> None:
        """Populate descriptor/slice maps and track overrides targeting inactive features."""
        for descriptor in self._descriptors:
            namespace = getattr(descriptor, "namespace", "")
            self._descriptor_map[namespace] = descriptor
            field_names = tuple(field.name for field in fields(descriptor.schema))  # type: ignore[arg-type]
            for field_name in field_names:
                self._field_map[field_name] = descriptor
            if self._descriptor_active(descriptor):
                slice_instance = self._materialize_slice(descriptor, field_names)
                validation_error = self._run_validators(
                    namespace, descriptor, slice_instance
                )
                if validation_error is None:
                    self._active_namespaces.add(namespace)
                    self._feature_slices[namespace] = slice_instance
                else:
                    if self._strict:
                        raise ValueError(
                            f"Feature '{namespace}' configuration failed validation: {validation_error}"
                        ) from validation_error
                    logger.warning(
                        "Validation failed for feature '%s' configuration: %s; using defaults",
                        namespace,
                        validation_error,
                    )
                    self._validation_failures[namespace] = str(validation_error)
                    self._active_namespaces.add(namespace)
                    self._feature_slices[namespace] = descriptor.create_defaults()
            else:
                self._inactive_fields[namespace] = field_names
                unused = tuple(
                    field_name
                    for field_name in field_names
                    if field_name in self._override_fields
                )
                if unused:
                    self._unused_fields[namespace] = unused

    def _descriptor_active(self, descriptor: object) -> bool:
        """Return True when all required features for ``descriptor`` are installed."""
        required = getattr(descriptor, "requires", ())
        if not required:
            return True
        missing = [
            feature for feature in required if feature not in self._installed_features
        ]
        return not missing

    def _materialize_slice(
        self, descriptor: object, field_names: tuple[str, ...]
    ) -> object:
        """Instantiate a slice object and seed it with values from the base config."""
        slice_instance = descriptor.create_defaults()
        for field_name in field_names:
            if not hasattr(slice_instance, field_name):
                continue
            value = getattr(self._base, field_name, None)
            setattr(slice_instance, field_name, self._copy_value(value))
        return slice_instance

    def _run_validators(
        self, namespace: str, descriptor: object, slice_instance: object
    ) -> Exception | None:
        """Execute descriptor validators and return the first failure."""
        validators = getattr(descriptor, "validators", ())
        for validator in validators:
            try:
                validator(slice_instance)
            except Exception as exc:  # noqa: BLE001 - feature validators are extensible
                return exc
        return None

    @staticmethod
    def _copy_value(value: Any) -> Any:
        """Delegate to Config._copy_value for nested slice cloning."""
        return Config._copy_value(value)

    def _raise_strict_error(self) -> None:
        """Raise when unused overrides target inactive feature namespaces."""
        details = ", ".join(
            f"{namespace} ({', '.join(fields)})"
            for namespace, fields in sorted(self._unused_fields.items())
        )
        raise ValueError(
            f"Configuration provided for inactive feature namespace(s): {details}"
        )


def diff_config_fields(config: Config) -> set[str]:
    """Return configuration attribute names that differ from defaults."""
    overrides: set[str] = set()
    defaults = config.config_defaults()
    for key in config.config_keys():
        default_value = defaults.get(key)
        if key == "cache" and not isinstance(default_value, CacheSettings):
            default_snapshot = CacheSettings()
        else:
            default_snapshot = default_value
        if getattr(config, key) != default_snapshot:
            overrides.add(key)
    return overrides
