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

"""Composition-owned layer instances for catalog image scenes."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from enum import Enum

from PySide6.QtGui import QColor

from ..scene.identity import base_image_layer_id


class CompositionLayerSourceKind(str, Enum):
    """Source kinds supported by composition-owned image scene layers."""

    CATALOG_IMAGE = "catalog-image"
    MASK = "mask"


@dataclass(frozen=True, slots=True)
class CompositionLayerInstance:
    """Store one reusable source's presentation inside an image scene."""

    layer_id: uuid.UUID
    source_kind: CompositionLayerSourceKind
    source_id: uuid.UUID
    visible: bool = True
    opacity: float = 1.0
    tint: QColor | None = None
    hit_test: bool = True
    selectable: bool = False
    role: str = "content"
    label: str | None = None

    def __post_init__(self) -> None:
        """Validate presentation and detach mutable color state."""
        if not 0.0 <= self.opacity <= 1.0:
            raise ValueError("layer opacity must be between 0.0 and 1.0")
        if self.tint is not None:
            object.__setattr__(self, "tint", QColor(self.tint))


class ImageSceneLayerStore:
    """Own ordered layer instances for catalog-backed image scenes."""

    def __init__(self) -> None:
        """Initialize an empty collection of image scene stacks."""
        self._layers_by_image: dict[uuid.UUID, list[CompositionLayerInstance]] = {}
        self._images_by_source: dict[
            tuple[CompositionLayerSourceKind, uuid.UUID], set[uuid.UUID]
        ] = {}
        self._revision = 0

    @property
    def revision(self) -> int:
        """Return the revision of ordered layer-instance state."""
        return self._revision

    def ensure_image(self, image_id: uuid.UUID) -> None:
        """Ensure an image scene begins with its catalog image layer."""
        if image_id in self._layers_by_image:
            return
        instance = CompositionLayerInstance(
            layer_id=base_image_layer_id(image_id),
            source_kind=CompositionLayerSourceKind.CATALOG_IMAGE,
            source_id=image_id,
            role="base-image",
        )
        self._layers_by_image[image_id] = [instance]
        self._index_source(image_id, instance)
        self._revision += 1

    def remove_image(self, image_id: uuid.UUID) -> tuple[CompositionLayerInstance, ...]:
        """Remove an image scene and return its former layer instances."""
        removed = tuple(self._layers_by_image.pop(image_id, ()))
        if not removed:
            return ()
        for instance in removed:
            self._unindex_source(image_id, instance)
        self._revision += 1
        return removed

    def clear(self) -> None:
        """Remove every image scene layer stack."""
        if not self._layers_by_image:
            return
        self._layers_by_image.clear()
        self._images_by_source.clear()
        self._revision += 1

    def layers_for_image(
        self, image_id: uuid.UUID
    ) -> tuple[CompositionLayerInstance, ...]:
        """Return an immutable ordered snapshot for one image scene."""
        return tuple(self._layers_by_image.get(image_id, ()))

    def layer(
        self, image_id: uuid.UUID, layer_id: uuid.UUID
    ) -> CompositionLayerInstance | None:
        """Return one layer instance from an image scene."""
        return next(
            (
                instance
                for instance in self._layers_by_image.get(image_id, ())
                if instance.layer_id == layer_id
            ),
            None,
        )

    def layer_for_source(
        self,
        image_id: uuid.UUID,
        source_kind: CompositionLayerSourceKind,
        source_id: uuid.UUID,
    ) -> CompositionLayerInstance | None:
        """Return the image scene instance for one source."""
        return next(
            (
                instance
                for instance in self._layers_by_image.get(image_id, ())
                if instance.source_kind == source_kind
                and instance.source_id == source_id
            ),
            None,
        )

    def image_ids_for_source(
        self,
        source_kind: CompositionLayerSourceKind,
        source_id: uuid.UUID,
    ) -> tuple[uuid.UUID, ...]:
        """Return image scenes containing instances of one source."""
        return tuple(
            sorted(
                self._images_by_source.get((source_kind, source_id), ()),
                key=str,
            )
        )

    def add_layer(
        self, image_id: uuid.UUID, instance: CompositionLayerInstance
    ) -> bool:
        """Append a layer instance to an existing image scene."""
        self.ensure_image(image_id)
        layers = self._layers_by_image[image_id]
        if any(candidate.layer_id == instance.layer_id for candidate in layers):
            return False
        if any(
            candidate.source_kind == instance.source_kind
            and candidate.source_id == instance.source_id
            for candidate in layers
        ):
            return False
        layers.append(instance)
        self._index_source(image_id, instance)
        self._revision += 1
        return True

    def remove_layer(self, image_id: uuid.UUID, layer_id: uuid.UUID) -> bool:
        """Remove one non-base layer instance from an image scene."""
        layers = self._layers_by_image.get(image_id)
        if not layers:
            return False
        instance = next(
            (candidate for candidate in layers if candidate.layer_id == layer_id), None
        )
        if (
            instance is None
            or instance.source_kind == CompositionLayerSourceKind.CATALOG_IMAGE
        ):
            return False
        layers.remove(instance)
        self._unindex_source(image_id, instance)
        self._revision += 1
        return True

    def reorder_layer(
        self, image_id: uuid.UUID, layer_id: uuid.UUID, target_index: int
    ) -> bool:
        """Move a layer to an exact cross-kind z-order index."""
        layers = self._layers_by_image.get(image_id)
        if not layers or target_index < 0 or target_index >= len(layers):
            return False
        current_index = next(
            (
                index
                for index, instance in enumerate(layers)
                if instance.layer_id == layer_id
            ),
            None,
        )
        if current_index is None or current_index == target_index:
            return False
        instance = layers.pop(current_index)
        layers.insert(target_index, instance)
        self._revision += 1
        return True

    def update_presentation(
        self,
        image_id: uuid.UUID,
        layer_id: uuid.UUID,
        *,
        opacity: float | None = None,
        tint: QColor | None = None,
    ) -> bool:
        """Replace presentation values for one layer instance."""
        layers = self._layers_by_image.get(image_id)
        if not layers:
            return False
        index = next(
            (
                position
                for position, instance in enumerate(layers)
                if instance.layer_id == layer_id
            ),
            None,
        )
        if index is None:
            return False
        current = layers[index]
        replacement = replace(
            current,
            opacity=current.opacity if opacity is None else opacity,
            tint=current.tint if tint is None else QColor(tint),
        )
        if replacement == current:
            return False
        layers[index] = replacement
        self._revision += 1
        return True

    def update_label(
        self,
        image_id: uuid.UUID,
        layer_id: uuid.UUID,
        label: str | None,
    ) -> bool:
        """Replace composition-owned display metadata for one instance."""
        layers = self._layers_by_image.get(image_id)
        if not layers:
            return False
        index = next(
            (
                position
                for position, instance in enumerate(layers)
                if instance.layer_id == layer_id
            ),
            None,
        )
        if index is None:
            return False
        normalized = label.strip() if isinstance(label, str) else None
        normalized = normalized or None
        replacement = replace(layers[index], label=normalized)
        if replacement == layers[index]:
            return False
        layers[index] = replacement
        self._revision += 1
        return True

    def _index_source(
        self, image_id: uuid.UUID, instance: CompositionLayerInstance
    ) -> None:
        """Record one source-to-image instance relationship."""
        key = (instance.source_kind, instance.source_id)
        self._images_by_source.setdefault(key, set()).add(image_id)

    def _unindex_source(
        self, image_id: uuid.UUID, instance: CompositionLayerInstance
    ) -> None:
        """Remove one source-to-image instance relationship."""
        key = (instance.source_kind, instance.source_id)
        image_ids = self._images_by_source.get(key)
        if image_ids is None:
            return
        image_ids.discard(image_id)
        if not image_ids:
            self._images_by_source.pop(key, None)
