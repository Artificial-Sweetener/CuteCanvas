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

from ..composition.layers import CompositionLayerInstance, CompositionLayerSourceKind
from .model import LayerDescriptor, LayerHitTest, SceneDescriptor
from .sources import CatalogImageSource


class CompositionLayerDescriptorFactory(Protocol):
    """Source-domain factory for one composition layer source kind."""

    source_kind: CompositionLayerSourceKind

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
    """Own complete cross-kind z-order assembly for default image scenes."""

    layer_instances: Callable[[uuid.UUID], tuple[CompositionLayerInstance, ...]]
    layer_revision: Callable[[], object]
    _factories: dict[CompositionLayerSourceKind, CompositionLayerDescriptorFactory] = (
        field(default_factory=dict, init=False)
    )

    def register_factory(self, factory: CompositionLayerDescriptorFactory) -> None:
        """Register the sole descriptor factory for one source kind."""
        if factory.source_kind in self._factories:
            raise ValueError(
                f"descriptor factory already registered for {factory.source_kind.value}"
            )
        self._factories[factory.source_kind] = factory

    def unregister_factory(self, factory: CompositionLayerDescriptorFactory) -> None:
        """Remove a previously registered descriptor factory by identity."""
        if self._factories.get(factory.source_kind) is factory:
            self._factories.pop(factory.source_kind)

    def revision(self) -> object:
        """Return composition and source-domain revisions affecting assembly."""
        return (
            self.layer_revision(),
            tuple(
                (kind.value, factory.revision())
                for kind, factory in self._factories.items()
            ),
        )

    def adapt_base_scene(
        self,
        base_scene: SceneDescriptor,
        image_id: uuid.UUID | None,
    ) -> SceneDescriptor:
        """Assemble all composition instances in their authoritative z-order."""
        if image_id is None:
            return base_scene
        instances = self.layer_instances(image_id)
        if not instances:
            return base_scene
        catalog_layers = {
            layer.source.image_id: layer
            for layer in base_scene.layers
            if isinstance(layer.source, CatalogImageSource)
        }
        layers: list[LayerDescriptor] = []
        for instance in instances:
            if instance.source_kind is CompositionLayerSourceKind.CATALOG_IMAGE:
                descriptor = self._catalog_descriptor(
                    catalog_layers.get(instance.source_id),
                    instance,
                )
            else:
                factory = self._factories.get(instance.source_kind)
                descriptor = (
                    None
                    if factory is None
                    else factory.descriptor(base_scene, instance)
                )
            if descriptor is not None:
                layers.append(replace(descriptor, label=instance.label))
        if not layers:
            return base_scene
        return replace(base_scene, layers=tuple(layers))

    @staticmethod
    def _catalog_descriptor(
        layer: LayerDescriptor | None,
        instance: CompositionLayerInstance,
    ) -> LayerDescriptor | None:
        """Apply composition presentation to one catalog descriptor."""
        if layer is None or layer.raster_bounds is None:
            return None
        return replace(
            layer,
            placement=instance.transform.map_bounds(layer.raster_bounds),
            transform=instance.transform,
            visible=instance.visible,
            opacity=instance.opacity,
            hit_test=LayerHitTest(enabled=instance.hit_test, role=instance.role),
            interaction=instance.interaction,
        )
