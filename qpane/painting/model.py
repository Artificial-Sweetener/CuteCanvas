#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Immutable source-neutral brush values shared by every paint target."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QPointF


class BrushOperation(str, Enum):
    """Describe how a target interprets brush coverage."""

    PAINT = "paint"
    ERASE = "erase"


@dataclass(frozen=True, slots=True)
class BrushDynamics:
    """Describe deterministic mappings from pointer state to dab properties."""

    pressure_size: float = 1.0
    pressure_opacity: float = 0.0
    minimum_pressure_ratio: float = 0.15
    pressure_gamma: float = 1.0
    position_jitter: float = 0.0
    size_jitter: float = 0.0
    angle_jitter: float = 0.0
    rotation_angle: float = 0.0
    tilt_angle: float = 0.0
    tangential_opacity: float = 0.0

    def __post_init__(self) -> None:
        """Reject non-finite or out-of-range dynamics values."""
        for name in (
            "pressure_size",
            "pressure_opacity",
            "minimum_pressure_ratio",
            "position_jitter",
            "size_jitter",
            "angle_jitter",
            "rotation_angle",
            "tilt_angle",
            "tangential_opacity",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be finite and between 0 and 1")
        if not math.isfinite(self.pressure_gamma) or self.pressure_gamma <= 0.0:
            raise ValueError("pressure_gamma must be finite and positive")


@dataclass(frozen=True, slots=True)
class BrushPreset:
    """Capture one durable deterministic brush configuration."""

    name: str = "Basic"
    size: float = 20.0
    hardness: float = 1.0
    opacity: float = 1.0
    flow: float = 1.0
    spacing: float = 0.2
    smoothing: float = 0.0
    angle: float = 0.0
    texture_strength: float = 0.0
    texture_scale: float = 8.0
    texture_seed: int = 0
    dynamics: BrushDynamics = BrushDynamics()

    def __post_init__(self) -> None:
        """Normalize only through validation so presets remain exact values."""
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("brush preset name must not be empty")
        if not math.isfinite(self.size) or self.size < 1.0:
            raise ValueError("brush size must be finite and at least 1")
        for name in (
            "hardness",
            "opacity",
            "flow",
            "smoothing",
            "texture_strength",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be finite and between 0 and 1")
        if not math.isfinite(self.spacing) or not 0.01 <= self.spacing <= 10.0:
            raise ValueError("brush spacing must be finite and between 0.01 and 10")
        if not math.isfinite(self.angle):
            raise ValueError("brush angle must be finite")
        if not math.isfinite(self.texture_scale) or self.texture_scale <= 0.0:
            raise ValueError("brush texture scale must be finite and positive")
        if not isinstance(self.texture_seed, int):
            raise TypeError("brush texture seed must be an integer")
        if not isinstance(self.dynamics, BrushDynamics):
            raise TypeError("dynamics must be BrushDynamics")


@dataclass(frozen=True, slots=True)
class BrushSample:
    """Capture one target-local pointer observation used by brush dynamics."""

    position: tuple[float, float]
    pressure: float = 1.0
    tilt_x: float = 0.0
    tilt_y: float = 0.0
    rotation: float = 0.0
    tangential_pressure: float = 0.0
    timestamp_ms: int = 0
    device_id: str = "mouse"

    def __post_init__(self) -> None:
        """Validate detached finite sample values."""
        values = (
            *self.position,
            self.pressure,
            self.tilt_x,
            self.tilt_y,
            self.rotation,
        )
        if any(not math.isfinite(float(value)) for value in values):
            raise ValueError("brush sample values must be finite")
        if not 0.0 <= float(self.pressure) <= 1.0:
            raise ValueError("brush pressure must be between 0 and 1")

    def point(self) -> QPointF:
        """Return the sample position as detached Qt geometry."""
        return QPointF(float(self.position[0]), float(self.position[1]))


@dataclass(frozen=True, slots=True)
class BrushStrokeSegment:
    """Describe one deterministic target-neutral brush segment."""

    start: tuple[float, float]
    end: tuple[float, float]
    start_diameter: float
    end_diameter: float
    operation: BrushOperation = BrushOperation.PAINT
    hardness: float = 1.0
    opacity: float = 1.0
    flow: float = 1.0
    spacing: float = 0.2
    angle: float = 0.0
    position_jitter: float = 0.0
    size_jitter: float = 0.0
    angle_jitter: float = 0.0
    rotation_angle: float = 0.0
    tilt_angle: float = 0.0
    tangential_opacity: float = 0.0
    seed: int = 0
    sequence: int = 0
    continuation: bool = False
    start_pressure: float = 1.0
    end_pressure: float = 1.0
    start_opacity: float = 1.0
    end_opacity: float = 1.0
    start_tilt_x: float = 0.0
    start_tilt_y: float = 0.0
    end_tilt_x: float = 0.0
    end_tilt_y: float = 0.0
    start_rotation: float = 0.0
    end_rotation: float = 0.0
    start_tangential_pressure: float = 0.0
    end_tangential_pressure: float = 0.0
    texture_strength: float = 0.0
    texture_scale: float = 8.0
    texture_seed: int = 0
    size_dynamics_applied: bool = False

    @classmethod
    def fixed(
        cls,
        start: tuple[float, float],
        end: tuple[float, float],
        diameter: float,
        erase: bool,
    ) -> BrushStrokeSegment:
        """Create the exact hard circular segment used by legacy mask painting."""
        return cls(
            start=start,
            end=end,
            start_diameter=diameter,
            end_diameter=diameter,
            operation=BrushOperation.ERASE if erase else BrushOperation.PAINT,
            size_dynamics_applied=True,
        )

    @property
    def erase(self) -> bool:
        """Return the legacy-compatible erase interpretation."""
        return self.operation is BrushOperation.ERASE

    @property
    def maximum_diameter(self) -> float:
        """Return the widest possible dab including configured size jitter."""
        base = max(1.0, float(self.start_diameter), float(self.end_diameter))
        return base * (1.0 + max(0.0, float(self.size_jitter)))

    def translated(self, delta_x: float, delta_y: float) -> BrushStrokeSegment:
        """Return this segment translated into another coordinate frame."""
        return BrushStrokeSegment(
            start=(self.start[0] + delta_x, self.start[1] + delta_y),
            end=(self.end[0] + delta_x, self.end[1] + delta_y),
            start_diameter=self.start_diameter,
            end_diameter=self.end_diameter,
            operation=self.operation,
            hardness=self.hardness,
            opacity=self.opacity,
            flow=self.flow,
            spacing=self.spacing,
            angle=self.angle,
            position_jitter=self.position_jitter,
            size_jitter=self.size_jitter,
            angle_jitter=self.angle_jitter,
            rotation_angle=self.rotation_angle,
            tilt_angle=self.tilt_angle,
            tangential_opacity=self.tangential_opacity,
            seed=self.seed,
            sequence=self.sequence,
            continuation=self.continuation,
            start_pressure=self.start_pressure,
            end_pressure=self.end_pressure,
            start_opacity=self.start_opacity,
            end_opacity=self.end_opacity,
            start_tilt_x=self.start_tilt_x,
            start_tilt_y=self.start_tilt_y,
            end_tilt_x=self.end_tilt_x,
            end_tilt_y=self.end_tilt_y,
            start_rotation=self.start_rotation,
            end_rotation=self.end_rotation,
            start_tangential_pressure=self.start_tangential_pressure,
            end_tangential_pressure=self.end_tangential_pressure,
            texture_strength=self.texture_strength,
            texture_scale=self.texture_scale,
            texture_seed=self.texture_seed,
            size_dynamics_applied=self.size_dynamics_applied,
        )


@dataclass(frozen=True, slots=True)
class BrushDab:
    """Describe one fully resolved deterministic dab."""

    center: tuple[float, float]
    diameter: float
    hardness: float
    opacity: float
    angle: float
    texture_strength: float = 0.0
    texture_scale: float = 8.0
    texture_seed: int = 0
