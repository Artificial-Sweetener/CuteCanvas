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

"""Validation helpers for the concurrency configuration section."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from ..core.config import Config


@dataclass(frozen=True)
class ThreadPolicy:
    """Normalized concurrency policy derived from host configuration."""

    max_workers: int
    max_pending_total: int | None = None
    category_priorities: dict[str, int] = field(default_factory=dict)
    category_limits: dict[str, int] = field(default_factory=dict)
    pending_limits: dict[str, int] = field(default_factory=dict)
    device_limits: dict[str, dict[str, int]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Clone mutable mappings so the frozen policy stays isolated."""
        object.__setattr__(self, "category_priorities", dict(self.category_priorities))
        object.__setattr__(self, "category_limits", dict(self.category_limits))
        object.__setattr__(self, "pending_limits", dict(self.pending_limits))
        object.__setattr__(
            self,
            "device_limits",
            {device: dict(limits) for device, limits in self.device_limits.items()},
        )

    def priority_for(self, category: str) -> int:
        """Return the submission priority for ``category``."""
        return self.category_priorities.get(category, 0)

    def limit_for(self, category: str) -> int | None:
        """Return the maximum active tasks for ``category`` when specified."""
        limit = self.category_limits.get(category)
        if limit is None or limit <= 0:
            return None
        return limit

    def device_limit(self, device: str | None, category: str) -> int | None:
        """Return the active task limit for ``category`` on ``device``."""
        if not device:
            return None
        device_limits = self.device_limits.get(device)
        if not device_limits:
            return None
        limit = device_limits.get(category)
        if limit is None or limit <= 0:
            return None
        return limit

    @classmethod
    def from_config(cls, config: Config) -> ThreadPolicy:
        """Construct a thread policy from an existing :class:`Config`.

        Args:
            config: Loaded configuration instance.

        Returns:
            ThreadPolicy reflecting the configuration's concurrency section.
        """
        return build_thread_policy(config)


def build_thread_policy(
    config: Config | Mapping[str, Any] | None = None,
    **overrides: Any,
) -> ThreadPolicy:
    """Create a :class:`ThreadPolicy` from config or explicit overrides.

    Args:
        config: QPane config instance or mapping containing concurrency keys.
        **overrides: Explicit values that override the base mapping.

    Returns:
        Normalised ThreadPolicy ready for executor consumption.

    Raises:
        TypeError: If ``config`` is not ``None``, a Config, or a mapping.
    """
    if config is None:
        base = _default_concurrency_map()
    elif _is_config_instance(config):
        base = config.concurrency
    elif isinstance(config, Mapping):
        base = dict(config)
    else:
        raise TypeError(
            "config must be a Config, mapping, or None when building ThreadPolicy"
        )
    if overrides:
        base = _merge_nested(base, overrides)
    max_workers = _coerce_positive_int(
        base.get("max_workers"), field_name="max_workers"
    )
    max_pending_total = _coerce_pending_limit(
        base.get("max_pending_total"), field_name="max_pending_total"
    )
    category_priorities = _normalize_priority_mapping(
        base.get("category_priorities"), field_name="category_priorities"
    )
    category_limits = _normalize_int_mapping(
        base.get("category_limits"), field_name="category_limits"
    )
    pending_limits = _normalize_pending_limits(base.get("pending_limits"))
    device_limits = _normalize_device_limits(base.get("device_limits"))
    return ThreadPolicy(
        max_workers=max_workers,
        max_pending_total=max_pending_total,
        category_priorities=category_priorities,
        category_limits=category_limits,
        pending_limits=pending_limits,
        device_limits=device_limits,
    )


def update_thread_policy(policy: ThreadPolicy, **overrides: Any) -> ThreadPolicy:
    """Return a new :class:`ThreadPolicy` that applies ``overrides`` to ``policy``.

    Args:
        policy: Existing policy instance used as the baseline.
        **overrides: Field overrides (``max_workers``, limit/priorities maps, etc.).

    Returns:
        Fresh :class:`ThreadPolicy` reflecting the merged values.

    Raises:
        TypeError: If ``policy`` is not a :class:`ThreadPolicy` instance or an
            override is not a mapping where required.
        ValueError: When numeric overrides fail validation.
    """
    if not isinstance(policy, ThreadPolicy):
        raise TypeError("policy must be a ThreadPolicy when updating concurrency")
    base = {
        "max_workers": policy.max_workers,
        "max_pending_total": policy.max_pending_total,
        "category_priorities": policy.category_priorities,
        "category_limits": policy.category_limits,
        "pending_limits": policy.pending_limits,
        "device_limits": policy.device_limits,
    }
    return build_thread_policy(base, **overrides)


def _config_class():
    """Import :class:`Config` lazily to dodge circular imports."""
    from ..core.config import Config as _Config

    return _Config


def _default_concurrency_map() -> dict[str, Any]:
    """Return a fresh copy of the default concurrency configuration.

    Returns:
        Deep copy of ``Config().concurrency`` for modification.
    """
    config_cls = _config_class()
    return config_cls().concurrency


def _merge_nested(
    base: Mapping[str, Any], overrides: Mapping[str, Any]
) -> dict[str, Any]:
    """Return a deep-merged mapping where overrides win.

    Args:
        base: Baseline configuration mapping.
        overrides: Mapping whose keys take precedence over ``base``.

    Returns:
        New mapping containing the merged values.
    """
    merged: dict[str, Any] = dict(base)
    for key, value in overrides.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = _merge_nested(merged[key], value)  # type: ignore[arg-type]
        else:
            merged[key] = value
    return merged


def _coerce_positive_int(value: Any, *, field_name: str, minimum: int = 1) -> int:
    """Validate integer inputs used for concurrency limits.

    Args:
        value: Candidate value supplied by config.
        field_name: Name used in error messages.
        minimum: Minimum accepted integer.

    Returns:
        Normalised integer value.

    Raises:
        TypeError: If the value cannot be coerced to an integer.
        ValueError: If the coerced value is below ``minimum``.
    """
    if isinstance(value, bool):  # bool is an int subclass but should be rejected
        raise TypeError(f"{field_name} must be an integer >= {minimum}, got {value!r}")
    try:
        integer = int(value)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
        raise TypeError(
            f"{field_name} must be an integer >= {minimum}, got {value!r}"
        ) from exc
    if integer < minimum:
        raise ValueError(f"{field_name} must be >= {minimum}, got {integer}")
    return integer


def _coerce_int(value: Any, *, field_name: str) -> int:
    """Validate integer inputs where negative values are allowed."""
    if isinstance(value, bool):  # bool is an int subclass but should be rejected
        raise TypeError(f"{field_name} must be an integer, got {value!r}")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
        raise TypeError(f"{field_name} must be an integer, got {value!r}") from exc


def _normalize_int_mapping(data: Any, *, field_name: str) -> dict[str, int]:
    """Return a ``str -> int`` mapping with validation.

    Args:
        data: Raw mapping provided via config or overrides.
        field_name: Prefix used to build descriptive error messages.

    Returns:
        Mapping whose keys are strings and whose values are integers.
    """
    if data is None:
        return {}
    if not isinstance(data, Mapping):
        raise TypeError(f"{field_name} must be a mapping of strings to integers")
    normalized: dict[str, int] = {}
    for key, value in data.items():
        if not isinstance(key, str):
            raise TypeError(f"{field_name} keys must be strings, got {key!r}")
        normalized[key] = _coerce_positive_int(
            value, field_name=f"{field_name}.{key}", minimum=0
        )
    return normalized


def _normalize_priority_mapping(data: Any, *, field_name: str) -> dict[str, int]:
    """Return a ``str -> int`` mapping for priorities that can be negative."""
    if data is None:
        return {}
    if not isinstance(data, Mapping):
        raise TypeError(f"{field_name} must be a mapping of strings to integers")
    normalized: dict[str, int] = {}
    for key, value in data.items():
        if not isinstance(key, str):
            raise TypeError(f"{field_name} keys must be strings, got {key!r}")
        normalized[key] = _coerce_int(value, field_name=f"{field_name}.{key}")
    return normalized


def _coerce_pending_limit(value: Any, *, field_name: str) -> int | None:
    """Validate pending queue limits, allowing None to mean unbounded.

    Args:
        value: Config value describing a pending limit.
        field_name: Name used in error messages.

    Returns:
        Integer limit or ``None`` when not bounded.
    """
    if value is None:
        return None
    return _coerce_positive_int(value, field_name=field_name, minimum=0)


def _normalize_pending_limits(data: Any) -> dict[str, int]:
    """Return a category->pending limit mapping with validation.

    Args:
        data: Mapping of category names to pending limits.

    Returns:
        Normalised mapping suitable for ThreadPolicy.
    """
    return _normalize_int_mapping(data, field_name="pending_limits")


def _normalize_device_limits(data: Any) -> dict[str, dict[str, int]]:
    """Return the device->category limit mapping with validation.

    Args:
        data: Mapping of device identifiers to per-category limits.

    Returns:
        Normalised two-level mapping for ThreadPolicy.
    """
    if data is None:
        return {}
    if not isinstance(data, Mapping):
        raise TypeError("device_limits must be a mapping of devices to category limits")
    normalized: dict[str, dict[str, int]] = {}
    for device, limits in data.items():
        if not isinstance(device, str):
            raise TypeError(f"device_limits keys must be strings, got {device!r}")
        normalized[device] = _normalize_int_mapping(
            limits, field_name=f"device_limits.{device}"
        )
    return normalized


def _is_config_instance(value: Any) -> bool:
    """Return ``True`` when ``value`` is an actual Config instance.

    Args:
        value: Object that might be a ``Config``.

    Returns:
        ``True`` if ``value`` is a ``Config``; ``False`` otherwise.
    """
    try:
        config_cls = _config_class()
    except (ImportError, AttributeError):
        return False
    return isinstance(value, config_cls)
