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

"""Private registries for feature-owned scene providers and source resolvers."""

from __future__ import annotations

from typing import Protocol

from .model import SceneDescriptor
from .providers import SceneContribution


class SceneContributionProvider(Protocol):
    """Provider that can contribute layers to a base scene."""

    def scene_contribution(
        self,
        base_scene: SceneDescriptor,
    ) -> SceneContribution | None:
        """Return scene content for ``base_scene`` or None when inactive."""
        ...


class SceneReplacementProvider(Protocol):
    """Provider that can replace default catalog scene resolution."""

    def scene_contribution(self) -> SceneContribution | None:
        """Return a replacement scene contribution or None when inactive."""
        ...


class SceneGeometryAdapter(Protocol):
    """Provider that can adapt base scene geometry before layer contribution."""

    def adapt_base_scene(
        self,
        base_scene: SceneDescriptor,
    ) -> SceneDescriptor:
        """Return the base scene geometry that feature contributions should target."""
        ...


class ScenePostProcessor(Protocol):
    """Apply transient descriptor changes after complete scene assembly."""

    def process_scene(self, scene: SceneDescriptor) -> SceneDescriptor:
        """Return a processed scene descriptor."""
        ...


class SceneProviderRegistry:
    """Own ordered private scene providers registered by feature domains."""

    def __init__(self) -> None:
        """Initialize an empty provider registry."""
        self._replacement_providers: list[SceneReplacementProvider] = []
        self._geometry_adapters: list[SceneGeometryAdapter] = []
        self._contribution_providers: list[SceneContributionProvider] = []
        self._post_processors: list[ScenePostProcessor] = []
        self._registration_revision = 0

    def register_replacement(
        self, provider: SceneReplacementProvider
    ) -> SceneReplacementProvider:
        """Register a provider that can replace default scene resolution."""
        if provider not in self._replacement_providers:
            self._replacement_providers.append(provider)
            self._registration_revision += 1
        return provider

    def unregister_replacement(self, provider: SceneReplacementProvider) -> None:
        """Remove a replacement provider."""
        previous_count = len(self._replacement_providers)
        self._replacement_providers = [
            candidate
            for candidate in self._replacement_providers
            if candidate is not provider
        ]
        if len(self._replacement_providers) != previous_count:
            self._registration_revision += 1

    def register_geometry_adapter(
        self, provider: SceneGeometryAdapter
    ) -> SceneGeometryAdapter:
        """Register a provider that can adapt default scene geometry."""
        if provider not in self._geometry_adapters:
            self._geometry_adapters.append(provider)
            self._registration_revision += 1
        return provider

    def unregister_geometry_adapter(self, provider: SceneGeometryAdapter) -> None:
        """Remove a previously registered scene geometry adapter."""
        previous_count = len(self._geometry_adapters)
        self._geometry_adapters = [
            candidate
            for candidate in self._geometry_adapters
            if candidate is not provider
        ]
        if len(self._geometry_adapters) != previous_count:
            self._registration_revision += 1

    def register_contribution(
        self, provider: SceneContributionProvider
    ) -> SceneContributionProvider:
        """Register a provider that can contribute layers to a scene."""
        if provider not in self._contribution_providers:
            self._contribution_providers.append(provider)
            self._registration_revision += 1
        return provider

    def unregister_contribution(self, provider: SceneContributionProvider) -> None:
        """Remove a contribution provider."""
        previous_count = len(self._contribution_providers)
        self._contribution_providers = [
            candidate
            for candidate in self._contribution_providers
            if candidate is not provider
        ]
        if len(self._contribution_providers) != previous_count:
            self._registration_revision += 1

    def register_post_processor(
        self, processor: ScenePostProcessor
    ) -> ScenePostProcessor:
        """Register a final scene processor if it is not already present."""
        if processor not in self._post_processors:
            self._post_processors.append(processor)
            self._registration_revision += 1
        return processor

    def unregister_post_processor(self, processor: ScenePostProcessor) -> None:
        """Remove a previously registered final scene processor."""
        previous_count = len(self._post_processors)
        self._post_processors = [
            candidate
            for candidate in self._post_processors
            if candidate is not processor
        ]
        if len(self._post_processors) != previous_count:
            self._registration_revision += 1

    def revision(self) -> tuple[object, ...]:
        """Return registry structure plus provider-owned dynamic revisions."""
        return (
            self._registration_revision,
            tuple(
                self._provider_revision(provider)
                for provider in self._replacement_providers
            ),
            tuple(
                self._provider_revision(provider)
                for provider in self._geometry_adapters
            ),
            tuple(
                self._provider_revision(provider)
                for provider in self._contribution_providers
            ),
            tuple(
                self._provider_revision(processor)
                for processor in self._post_processors
            ),
        )

    def process_scene(self, scene: SceneDescriptor) -> SceneDescriptor:
        """Apply registered final processors in stable registration order."""
        processed = scene
        for processor in self._post_processors:
            processed = processor.process_scene(processed)
        return processed

    def replacement_contributions(self) -> tuple[SceneContribution, ...]:
        """Return active replacement scene contributions."""
        return tuple(
            contribution
            for provider in self._replacement_providers
            if (contribution := provider.scene_contribution()) is not None
        )

    def adapt_base_scene(self, base_scene: SceneDescriptor) -> SceneDescriptor:
        """Return ``base_scene`` after registered geometry adapters have run."""
        adapted = base_scene
        for provider in self._geometry_adapters:
            adapted = provider.adapt_base_scene(adapted)
        return adapted

    def contributions_for(
        self, base_scene: SceneDescriptor
    ) -> tuple[SceneContribution, ...]:
        """Return active feature contributions for ``base_scene``."""
        return tuple(
            contribution
            for provider in self._contribution_providers
            if (contribution := provider.scene_contribution(base_scene)) is not None
        )

    @staticmethod
    def _provider_revision(provider: object) -> object:
        """Return a provider's dynamic token or its stable identity."""
        revision_getter = getattr(provider, "revision", None)
        if callable(revision_getter):
            return revision_getter()
        return id(provider)
