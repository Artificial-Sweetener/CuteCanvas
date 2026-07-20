#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Compile immutable presets and sampled pressure into semantic segments."""

from __future__ import annotations

from dataclasses import replace

from .model import BrushDynamics, BrushPreset, BrushStrokeSegment


class BrushStrokeCompiler:
    """Apply one preset consistently before any paint target sees a segment."""

    def compile(
        self,
        segment: BrushStrokeSegment,
        preset: BrushPreset,
    ) -> BrushStrokeSegment:
        """Return a configured deterministic segment for target compositing."""
        dynamics = preset.dynamics
        start_curve = self.pressure_curve(segment.start_pressure, dynamics)
        end_curve = self.pressure_curve(segment.end_pressure, dynamics)
        start_diameter = (
            segment.start_diameter
            if segment.size_dynamics_applied
            else preset.size * self._mapped_factor(start_curve, dynamics.pressure_size)
        )
        end_diameter = (
            segment.end_diameter
            if segment.size_dynamics_applied
            else preset.size * self._mapped_factor(end_curve, dynamics.pressure_size)
        )
        return replace(
            segment,
            start_diameter=start_diameter,
            end_diameter=end_diameter,
            start_opacity=self._mapped_factor(
                start_curve,
                dynamics.pressure_opacity,
            ),
            end_opacity=self._mapped_factor(
                end_curve,
                dynamics.pressure_opacity,
            ),
            hardness=preset.hardness,
            opacity=preset.opacity,
            flow=preset.flow,
            spacing=preset.spacing,
            angle=preset.angle,
            position_jitter=dynamics.position_jitter,
            size_jitter=dynamics.size_jitter,
            angle_jitter=dynamics.angle_jitter,
            rotation_angle=dynamics.rotation_angle,
            tilt_angle=dynamics.tilt_angle,
            tangential_opacity=dynamics.tangential_opacity,
            texture_strength=preset.texture_strength,
            texture_scale=preset.texture_scale,
            texture_seed=preset.texture_seed,
        )

    def diameter_for_pressure(self, pressure: float, preset: BrushPreset) -> float:
        """Return the preset diameter after its pressure-size mapping."""
        curve = self.pressure_curve(pressure, preset.dynamics)
        return preset.size * self._mapped_factor(
            curve,
            preset.dynamics.pressure_size,
        )

    @staticmethod
    def pressure_curve(pressure: float, dynamics: BrushDynamics) -> float:
        """Map normalized pressure through the preset's floor and gamma curve."""
        normalized = min(1.0, max(0.0, float(pressure))) ** dynamics.pressure_gamma
        floor = dynamics.minimum_pressure_ratio
        return floor + (1.0 - floor) * normalized

    @staticmethod
    def _mapped_factor(curve: float, amount: float) -> float:
        """Blend an enabled dynamic between a neutral factor and its curve."""
        return 1.0 + float(amount) * (curve - 1.0)
