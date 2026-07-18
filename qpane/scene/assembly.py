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

"""Assemble complete ordered scenes before rendering begins."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSize

from .default_scene import DefaultCatalogSceneProvider
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

    def resolve_catalog_image(
        self,
        *,
        image_id: uuid.UUID,
        image_size: QSize,
        source_path: Path | None,
        source_revision: int,
    ) -> SceneDescriptor | None:
        """Build the complete scene for one active catalog image."""
        replacements = self.resolve_replacement()
        if replacements is not None:
            return replacements
        contribution = DefaultCatalogSceneProvider(
            image_id=image_id,
            image_size=image_size,
            source_path=source_path,
            revision=source_revision,
        ).scene_contribution()
        if contribution is None:
            return None
        base_scene = self._providers.adapt_base_scene(
            contribution.scene,
            image_id,
        )
        contributions = [SceneContribution(base_scene, order=0)]
        contributions.extend(self._providers.contributions_for(base_scene, image_id))
        scene = self._resolve(tuple(contributions))
        return None if scene is None else self._providers.process_scene(scene)

    def resolve_replacement(self) -> SceneDescriptor | None:
        """Resolve the active replacement scene when one is registered."""
        scene = self._resolve(self._providers.replacement_contributions())
        return None if scene is None else self._providers.process_scene(scene)

    @staticmethod
    def _resolve(
        contributions: tuple[SceneContribution, ...],
    ) -> SceneDescriptor | None:
        """Resolve a complete scene from already materialized contributions."""
        return SceneResolver(
            providers=tuple(_StaticSceneProvider(item) for item in contributions)
        ).resolve()
