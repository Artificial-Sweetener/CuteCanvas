#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Ordered assembly of composition layer instances into scene descriptors."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Protocol

from ..composition.layers import CompositionLayerInstance
from .model import LayerDescriptor, SceneDescriptor
from .source_references import LayerSourceReference


class CompositionLayerDescriptorFactory(Protocol):
    """Source-domain factory for one composition layer source kind."""

    source_type: type[LayerSourceReference]

    def descriptor(
        self,
        scene: SceneDescriptor,
        instance: CompositionLayerInstance,
    ) -> LayerDescriptor | None:
        """Resolve one composition instance into a scene descriptor."""
        ...

    def revision(self) -> object:
        """Return source-domain state affecting resolved descriptors."""
        ...


@dataclass(slots=True)
class CompositionLayerSceneAssembler:
    """Own complete cross-kind z-order assembly for composition documents."""

    layer_instances: Callable[[uuid.UUID], tuple[CompositionLayerInstance, ...]]
    layer_revision: Callable[[], object]
    _factories: dict[type[LayerSourceReference], CompositionLayerDescriptorFactory] = (
        field(default_factory=dict, init=False)
    )

    def register_factory(self, factory: CompositionLayerDescriptorFactory) -> None:
        """Register the sole descriptor factory for one source kind."""
        if factory.source_type in self._factories:
            raise ValueError(
                "descriptor factory already registered for "
                f"{factory.source_type.__name__}"
            )
        self._factories[factory.source_type] = factory

    def unregister_factory(self, factory: CompositionLayerDescriptorFactory) -> None:
        """Remove a previously registered descriptor factory by identity."""
        if self._factories.get(factory.source_type) is factory:
            self._factories.pop(factory.source_type)

    def revision(self) -> object:
        """Return composition and source-domain revisions affecting assembly."""
        return (
            self.layer_revision(),
            tuple(
                (source_type.__name__, factory.revision())
                for source_type, factory in self._factories.items()
            ),
        )

    def assemble(self, document: SceneDescriptor) -> SceneDescriptor:
        """Resolve every document instance in its authoritative z-order."""
        return self._assemble_instances(
            document,
            self.layer_instances(document.scene_id),
        )

    def _assemble_instances(
        self,
        document: SceneDescriptor,
        instances: tuple[CompositionLayerInstance, ...],
    ) -> SceneDescriptor:
        """Resolve one already-addressed instance stack through registered factories."""
        layers: list[LayerDescriptor] = []
        for instance in instances:
            factory = self._factories.get(type(instance.source))
            descriptor = (
                None if factory is None else factory.descriptor(document, instance)
            )
            if descriptor is not None:
                layers.append(replace(descriptor, label=instance.label))
        return replace(document, layers=tuple(layers))

    def adapt_base_scene(
        self,
        base_scene: SceneDescriptor,
        image_id: uuid.UUID | None,
    ) -> SceneDescriptor:
        """Adapt a catalog-seeded scene through the same composition assembly path."""
        if image_id is None:
            return base_scene
        return self._assemble_instances(base_scene, self.layer_instances(image_id))
