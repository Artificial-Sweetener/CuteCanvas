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
"""Deterministic brush dab emission independent of paint target format."""

from __future__ import annotations

import math
import random

from .model import BrushDab, BrushStrokeSegment


class BrushDabEngine:
    """Expand semantic stroke segments into reproducible ordered dabs."""

    def segment_dabs(self, segment: BrushStrokeSegment) -> tuple[BrushDab, ...]:
        """Return stable dabs for one variable-width segment."""
        start_x, start_y = map(float, segment.start)
        end_x, end_y = map(float, segment.end)
        delta_x = end_x - start_x
        delta_y = end_y - start_y
        forward = segment.tip_transform.inverted()
        if forward is None:
            return ()
        scene_delta_x = forward.m11 * delta_x + forward.m21 * delta_y
        scene_delta_y = forward.m12 * delta_x + forward.m22 * delta_y
        distance = math.hypot(scene_delta_x, scene_delta_y)
        minimum_diameter = max(
            1.0,
            min(float(segment.start_diameter), float(segment.end_diameter)),
        )
        spacing = max(0.5, minimum_diameter * float(segment.spacing))
        if distance == 0.0:
            return (self._dab(segment, 0, 1, start_x, start_y, 0.0, 0.0),)
        step_count = max(1, math.ceil(distance / spacing))
        first_step = 1 if segment.continuation else 0
        return tuple(
            self._dab(segment, step, step_count, start_x, start_y, delta_x, delta_y)
            for step in range(first_step, step_count + 1)
        )

    @staticmethod
    def _dab(
        segment: BrushStrokeSegment,
        step: int,
        step_count: int,
        start_x: float,
        start_y: float,
        delta_x: float,
        delta_y: float,
    ) -> BrushDab:
        """Resolve one dab without retaining mutable random state."""
        fraction = step / step_count
        randomizer = random.Random(
            (int(segment.seed) << 32) ^ (int(segment.sequence) << 16) ^ step
        )
        diameter = (
            float(segment.start_diameter)
            + (float(segment.end_diameter) - float(segment.start_diameter)) * fraction
        )
        diameter *= 1.0 + randomizer.uniform(
            -float(segment.size_jitter), float(segment.size_jitter)
        )
        jitter_radius = max(0.0, diameter * float(segment.position_jitter))
        jitter_angle = randomizer.random() * math.tau
        jitter_distance = math.sqrt(randomizer.random()) * jitter_radius
        jitter_x = math.cos(jitter_angle) * jitter_distance
        jitter_y = math.sin(jitter_angle) * jitter_distance
        tip_transform = segment.tip_transform
        center = (
            start_x
            + delta_x * fraction
            + tip_transform.m11 * jitter_x
            + tip_transform.m21 * jitter_y,
            start_y
            + delta_y * fraction
            + tip_transform.m12 * jitter_x
            + tip_transform.m22 * jitter_y,
        )
        rotation = _interpolate(
            segment.start_rotation,
            segment.end_rotation,
            fraction,
        )
        tilt_x = _interpolate(segment.start_tilt_x, segment.end_tilt_x, fraction)
        tilt_y = _interpolate(segment.start_tilt_y, segment.end_tilt_y, fraction)
        tilt_direction = (
            math.degrees(math.atan2(tilt_y, tilt_x))
            if tilt_x != 0.0 or tilt_y != 0.0
            else 0.0
        )
        angle = (
            float(segment.angle)
            + rotation * float(segment.rotation_angle)
            + tilt_direction * float(segment.tilt_angle)
            + randomizer.uniform(
                -180.0 * float(segment.angle_jitter),
                180.0 * float(segment.angle_jitter),
            )
        )
        opacity = (
            float(segment.start_opacity)
            + (float(segment.end_opacity) - float(segment.start_opacity)) * fraction
        )
        tangential = _interpolate(
            segment.start_tangential_pressure,
            segment.end_tangential_pressure,
            fraction,
        )
        tangential_factor = 1.0 + float(segment.tangential_opacity) * (
            min(1.0, max(-1.0, tangential)) - 1.0
        )
        return BrushDab(
            center=center,
            diameter=max(1.0, diameter),
            hardness=float(segment.hardness),
            opacity=(
                opacity
                * float(segment.opacity)
                * float(segment.flow)
                * tangential_factor
            ),
            angle=angle,
            texture_strength=float(segment.texture_strength),
            texture_scale=float(segment.texture_scale),
            texture_seed=int(segment.texture_seed) ^ int(segment.sequence),
            tip_transform=segment.tip_transform,
        )


def _interpolate(start: float, end: float, fraction: float) -> float:
    """Linearly interpolate one sampled dynamic value."""
    return float(start) + (float(end) - float(start)) * float(fraction)
