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
"""Byte-bounded immutable brush-tip products shared by paint compositors."""

from __future__ import annotations

import math
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class BrushTipKey:
    """Identify one reusable procedural round-tip alpha product."""

    diameter_quarters: int
    hardness_millis: int
    texture_millis: int
    texture_scale_quarters: int
    texture_seed: int
    angle_degrees: int


@dataclass(frozen=True, slots=True)
class BrushOpacityTipKey:
    """Identify one reusable opacity-adjusted tip product."""

    tip: BrushTipKey
    opacity: float


class BrushTipCache:
    """Own a thread-safe least-recently-used cache of readonly tip alpha."""

    def __init__(self, budget_bytes: int = 8 * 1024 * 1024) -> None:
        """Initialize an empty cache with a strict byte ceiling."""
        self._budget_bytes = max(0, int(budget_bytes))
        self._usage_bytes = 0
        self._entries: OrderedDict[
            BrushTipKey | BrushOpacityTipKey,
            np.ndarray,
        ] = OrderedDict()
        self._lock = threading.RLock()
        self._usage_changed: Callable[[int], None] | None = None

    @property
    def usage_bytes(self) -> int:
        """Return exact retained array bytes."""
        with self._lock:
            return self._usage_bytes

    @property
    def entry_count(self) -> int:
        """Return the number of retained tip variants."""
        with self._lock:
            return len(self._entries)

    def set_usage_changed(self, callback: Callable[[int], None] | None) -> None:
        """Install the cache-coordinator usage reporter."""
        with self._lock:
            self._usage_changed = callback

    def set_budget(self, budget_bytes: int) -> None:
        """Apply a new strict budget and evict oldest entries immediately."""
        with self._lock:
            self._budget_bytes = max(0, int(budget_bytes))
            self._trim_locked(self._budget_bytes)
            usage = self._usage_bytes
        self._report_usage(usage)

    def trim_to(self, target_bytes: int) -> None:
        """Evict oldest tips until usage does not exceed ``target_bytes``."""
        with self._lock:
            self._trim_locked(max(0, int(target_bytes)))
            usage = self._usage_bytes
        self._report_usage(usage)

    def tip(
        self,
        *,
        diameter: float,
        hardness: float,
        texture_strength: float,
        texture_scale: float,
        texture_seed: int,
        angle: float,
    ) -> np.ndarray:
        """Return one deterministic readonly 8-bit tip alpha image."""
        key = _tip_key(
            diameter=diameter,
            hardness=hardness,
            texture_strength=texture_strength,
            texture_scale=texture_scale,
            texture_seed=texture_seed,
            angle=angle,
        )
        return self._get_or_create(key, lambda: _generate_tip(key))

    def opacity_tip(
        self,
        *,
        diameter: float,
        hardness: float,
        texture_strength: float,
        texture_scale: float,
        texture_seed: int,
        angle: float,
        opacity: float,
    ) -> np.ndarray:
        """Return one cached readonly tip with opacity already applied."""
        tip_key = _tip_key(
            diameter=diameter,
            hardness=hardness,
            texture_strength=texture_strength,
            texture_scale=texture_scale,
            texture_seed=texture_seed,
            angle=angle,
        )
        normalized_opacity = min(1.0, max(0.0, float(opacity)))
        if normalized_opacity == 1.0:
            return self._get_or_create(tip_key, lambda: _generate_tip(tip_key))
        key = BrushOpacityTipKey(tip_key, normalized_opacity)

        def generate() -> np.ndarray:
            """Apply opacity once for every compositor sharing this cache."""
            tip = self._get_or_create(tip_key, lambda: _generate_tip(tip_key))
            result = np.rint(tip.astype(np.float32) * normalized_opacity).astype(
                np.uint8
            )
            result.flags.writeable = False
            return result

        return self._get_or_create(key, generate)

    def _get_or_create(
        self,
        key: BrushTipKey | BrushOpacityTipKey,
        factory: Callable[[], np.ndarray],
    ) -> np.ndarray:
        """Return one cache product, generating it outside the cache lock."""
        with self._lock:
            cached = self._entries.pop(key, None)
            if cached is not None:
                self._entries[key] = cached
                return cached
        generated = factory()
        with self._lock:
            cached = self._entries.pop(key, None)
            if cached is not None:
                self._entries[key] = cached
                return cached
            if generated.nbytes <= self._budget_bytes:
                self._entries[key] = generated
                self._usage_bytes += generated.nbytes
                self._trim_locked(self._budget_bytes)
            usage = self._usage_bytes
        self._report_usage(usage)
        return generated

    def _trim_locked(self, target_bytes: int) -> None:
        """Trim entries while the caller holds ``_lock``."""
        while self._entries and self._usage_bytes > target_bytes:
            _key, alpha = self._entries.popitem(last=False)
            self._usage_bytes -= alpha.nbytes

    def _report_usage(self, usage_bytes: int) -> None:
        """Publish usage without holding the cache lock."""
        callback = self._usage_changed
        if callback is not None:
            callback(usage_bytes)


def _tip_key(
    *,
    diameter: float,
    hardness: float,
    texture_strength: float,
    texture_scale: float,
    texture_seed: int,
    angle: float,
) -> BrushTipKey:
    """Normalize public brush parameters into one deterministic cache key."""
    return BrushTipKey(
        diameter_quarters=max(4, round(float(diameter) * 4.0)),
        hardness_millis=round(min(1.0, max(0.0, hardness)) * 1000.0),
        texture_millis=round(min(1.0, max(0.0, texture_strength)) * 1000.0),
        texture_scale_quarters=max(1, round(float(texture_scale) * 4.0)),
        texture_seed=int(texture_seed),
        angle_degrees=round(float(angle)) % 360,
    )


def _generate_tip(key: BrushTipKey) -> np.ndarray:
    """Build one anti-aliased radial tip with deterministic procedural grain."""
    diameter = key.diameter_quarters / 4.0
    size = max(3, math.ceil(diameter) + 2)
    coordinates = np.arange(size, dtype=np.float32) - (size - 1) / 2.0
    y_grid, x_grid = np.meshgrid(coordinates, coordinates, indexing="ij")
    radius = max(0.5, diameter / 2.0)
    distance = np.sqrt(x_grid * x_grid + y_grid * y_grid)
    normalized = distance / radius
    hardness = key.hardness_millis / 1000.0
    feather_width = max(1e-4, 1.0 - hardness)
    alpha = np.clip((1.0 - normalized) / feather_width, 0.0, 1.0)
    if hardness >= 0.999:
        alpha = np.clip(radius + 0.5 - distance, 0.0, 1.0)
    texture_strength = key.texture_millis / 1000.0
    if texture_strength > 0.0:
        radians = math.radians(key.angle_degrees)
        rotated_x = x_grid * math.cos(radians) - y_grid * math.sin(radians)
        rotated_y = x_grid * math.sin(radians) + y_grid * math.cos(radians)
        scale = key.texture_scale_quarters / 4.0
        phase = float(key.texture_seed % 104729)
        noise = np.sin(
            rotated_x * (12.9898 / scale) + rotated_y * (78.233 / scale) + phase * 0.001
        )
        noise = noise * 0.5 + 0.5
        alpha *= (1.0 - texture_strength) + texture_strength * noise
    result = np.rint(alpha * 255.0).astype(np.uint8)
    result.flags.writeable = False
    return result
