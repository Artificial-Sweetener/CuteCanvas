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

"""Assemble complete provider-owned scenes before rendering begins."""

from __future__ import annotations

from dataclasses import dataclass

from .model import SceneDescriptor
from .providers import SceneContribution, SceneResolver
from .registry import SceneProviderRegistry


@dataclass(frozen=True, slots=True)
class _StaticSceneProvider:
    """Expose a prebuilt contribution to the generic resolver."""

    contribution: SceneContribution

    def scene_contribution(self) -> SceneContribution:
        """Return the stored contribution."""
        return self.contribution


class SceneAssembly:
    """Own complete scene construction from registered domain providers."""

    def __init__(self, providers: SceneProviderRegistry) -> None:
        """Capture the provider registry used for scene construction."""
        self._providers = providers

    def resolve_scene(self) -> SceneDescriptor | None:
        """Resolve the active document through shared scene extension stages."""
        base_scene = self._resolve(self._providers.replacement_contributions())
        if base_scene is None:
            return None
        adapted = self._providers.adapt_base_scene(base_scene)
        contributions = [SceneContribution(adapted, order=0)]
        contributions.extend(self._providers.contributions_for(adapted))
        scene = self._resolve(tuple(contributions))
        return None if scene is None else self._providers.process_scene(scene)

    @staticmethod
    def _resolve(
        contributions: tuple[SceneContribution, ...],
    ) -> SceneDescriptor | None:
        """Resolve a complete scene from already materialized contributions."""
        return SceneResolver(
            providers=tuple(_StaticSceneProvider(item) for item in contributions)
        ).resolve()
