#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Focused host-facing vector editor delegation behind the QPane facade."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QTransform

from ..composition import CompositionService
from ..coverage import CoverageCombineMode
from ..scene.layer_selection import SceneLayerSelectionController
from ..scene.model import LayerInteractionPolicy, LayerPlacement, SceneDescriptor
from ..scene.raster import RasterBounds
from .conversion import VectorConversionService
from .editing import VectorEditService
from .effects import VectorMaskController
from .layers import VectorLayerController
from .node_edit import VectorNodeEditController
from .presentation import document_state, selection_state
from .public import (
    QPaneTextFontResolution,
    QPaneVectorDocumentState,
    QPaneVectorMaskState,
    QPaneVectorNodeSelectionState,
    QPaneVectorSelectionState,
    QPaneVectorTextEditState,
    VectorPathCommand,
    VectorShapeKind,
    VectorStyle,
    VectorTextContent,
)
from .selection import VectorObjectSelectionController
from .source_reference import VectorDocumentReference
from .store import VectorAssetStore
from .targets import VectorAuthoringTargetResolver
from .text_edit import VectorTextEditController


class VectorHostFacade:
    """Resolve active composition context and delegate vector operations."""

    def __init__(
        self,
        *,
        compositions: CompositionService,
        assets: VectorAssetStore,
        layers: VectorLayerController,
        edits: VectorEditService,
        selection: VectorObjectSelectionController,
        current_scene: Callable[[], SceneDescriptor | None],
        current_public_scene_id: Callable[[], uuid.UUID | None],
        changed: Callable[[], None],
        conversions: VectorConversionService,
        masks: VectorMaskController,
        targets: VectorAuthoringTargetResolver,
        layer_selection: SceneLayerSelectionController,
        nodes: VectorNodeEditController,
        texts: VectorTextEditController,
    ) -> None:
        """Bind vector owners and active-scene lookup functions."""
        self._compositions = compositions
        self._assets = assets
        self._layers = layers
        self._edits = edits
        self._selection = selection
        self._current_scene = current_scene
        self._current_public_scene_id = current_public_scene_id
        self._changed = changed
        self._conversions = conversions
        self._masks = masks
        self._targets = targets
        self._layer_selection = layer_selection
        self._nodes = nodes
        self._texts = texts

    @property
    def texts(self) -> VectorTextEditController:
        """Return the focused semantic-text editing owner."""
        return self._texts

    def create_layer(
        self,
        size: QSize | None,
        *,
        label: str,
        interaction: LayerInteractionPolicy,
    ) -> uuid.UUID | None:
        """Create an undoable empty vector layer within the active scene."""
        scene = self._current_scene()
        if scene is None:
            return None
        width = max(1, round(scene.bounds.width)) if size is None else size.width()
        height = max(1, round(scene.bounds.height)) if size is None else size.height()
        bounds = RasterBounds(0, 0, width, height)
        created = self._layers.create(
            bounds,
            label=label,
            interaction=interaction,
            placement=LayerPlacement(
                scene.bounds.x,
                scene.bounds.y,
                float(width),
                float(height),
            ),
        )
        if created is None:
            return None
        layer_id, _vector_id = created
        self._changed()
        return layer_id

    def document_state(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> QPaneVectorDocumentState | None:
        """Return one active vector layer's detached semantic state."""
        context = self._context(scene_id, layer_id)
        if context is None:
            return None
        _scope_id, vector_id, _resolved_scene_id = context
        document = self._assets.get(vector_id)
        return (
            None if document is None else document_state(scene_id, layer_id, document)
        )

    def add_shape(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        shape: VectorShapeKind,
        bounds: QRectF,
        style: VectorStyle,
    ) -> uuid.UUID | None:
        """Add one parametric shape through composition chronology."""
        context = self._context(scene_id, layer_id)
        if context is None:
            return None
        _scope_id, vector_id, resolved_scene_id = context
        return self._edits.add_shape(
            resolved_scene_id,
            layer_id,
            vector_id,
            shape,
            bounds,
            style,
        )

    def add_path(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        commands: tuple[VectorPathCommand, ...],
        style: VectorStyle,
    ) -> uuid.UUID | None:
        """Add one durable command path through composition chronology."""
        context = self._context(scene_id, layer_id)
        if context is None:
            return None
        _scope_id, vector_id, resolved_scene_id = context
        return self._edits.add_path(
            resolved_scene_id,
            layer_id,
            vector_id,
            commands,
            style,
        )

    def add_text(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        bounds: QRectF,
        content: VectorTextContent,
    ) -> uuid.UUID | None:
        """Add semantic text through composition chronology."""
        context = self._context(scene_id, layer_id)
        if context is None:
            return None
        _scope_id, vector_id, resolved_scene_id = context
        return self._edits.add_text(
            resolved_scene_id, layer_id, vector_id, bounds, content
        )

    def update_text(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_id: uuid.UUID,
        *,
        bounds: QRectF | None = None,
        content: VectorTextContent | None = None,
    ) -> bool:
        """Update semantic text content or its layout box atomically."""
        context = self._context(scene_id, layer_id)
        if context is None:
            return False
        _scope_id, vector_id, resolved_scene_id = context
        return self._edits.update_text(
            resolved_scene_id,
            layer_id,
            vector_id,
            object_id,
            bounds=bounds,
            content=content,
        )

    def begin_text_edit(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_id: uuid.UUID,
    ) -> bool:
        """Begin one in-place text session after resolving public context."""
        if self._context(scene_id, layer_id) is None:
            return False
        return self._texts.begin_object(layer_id, object_id)

    def text_edit_state(self) -> QPaneVectorTextEditState | None:
        """Return active text state with the public scene identity."""
        state = self._texts.state()
        public_scene_id = self._current_public_scene_id()
        scene = self._current_scene()
        if (
            state is None
            or public_scene_id is None
            or scene is None
            or state.scene_id != scene.scene_id
        ):
            return None
        return QPaneVectorTextEditState(
            public_scene_id,
            state.layer_id,
            state.object_id,
            state.text,
            state.cursor,
            state.is_new,
        )

    def text_font_resolutions(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_id: uuid.UUID,
    ) -> tuple[QPaneTextFontResolution, ...]:
        """Return font fallback diagnostics for one semantic text object."""
        if self._context(scene_id, layer_id) is None:
            return ()
        return self._texts.font_resolutions(layer_id, object_id)

    def convert_text_to_paths(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_id: uuid.UUID,
    ) -> uuid.UUID | None:
        """Begin semantic-text conversion into painted outline paths."""
        context = self._context(scene_id, layer_id)
        if context is None:
            return None
        scope_id, vector_id, resolved_scene_id = context
        return self._conversions.request_text_paths(
            composition_id=scope_id,
            history_scope_id=resolved_scene_id,
            public_scene_id=scene_id,
            layer_id=layer_id,
            vector_id=vector_id,
            object_id=object_id,
        )

    def update_object(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_id: uuid.UUID,
        *,
        transform: QTransform | None = None,
        style: VectorStyle | None = None,
    ) -> bool:
        """Update one stable object with a single chronological command."""
        context = self._context(scene_id, layer_id)
        if context is None:
            return False
        _scope_id, vector_id, resolved_scene_id = context
        return self._edits.update_object(
            resolved_scene_id,
            layer_id,
            vector_id,
            object_id,
            transform=transform,
            style=style,
        )

    def remove_object(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_id: uuid.UUID,
    ) -> bool:
        """Remove one stable object with a single chronological command."""
        context = self._context(scene_id, layer_id)
        if context is None:
            return False
        _scope_id, vector_id, resolved_scene_id = context
        changed = self._edits.remove_object(
            resolved_scene_id,
            layer_id,
            vector_id,
            object_id,
        )
        if changed and self._selection.selection is not None:
            retained = tuple(
                candidate
                for candidate in self._selection.selection.object_ids
                if candidate != object_id
            )
            self._selection.set(resolved_scene_id, layer_id, retained)
        return changed

    def reorder_object(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_id: uuid.UUID,
        index: int,
    ) -> bool:
        """Move one object to a stable document order index."""
        context = self._context(scene_id, layer_id)
        if context is None:
            return False
        _scope_id, vector_id, resolved_scene_id = context
        return self._edits.reorder_object(
            resolved_scene_id,
            layer_id,
            vector_id,
            object_id,
            index,
        )

    def set_selection(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_ids: tuple[uuid.UUID, ...],
    ) -> bool:
        """Select existing vector objects independently of pixel selection."""
        context = self._context(scene_id, layer_id)
        if context is None:
            return False
        _scope_id, vector_id, resolved_scene_id = context
        document = self._assets.get(vector_id)
        if document is None or any(
            document.object(object_id) is None for object_id in object_ids
        ):
            return False
        changed = self._selection.set(resolved_scene_id, layer_id, object_ids)
        self._nodes.synchronize()
        return changed

    def selection_state(self) -> QPaneVectorSelectionState | None:
        """Return the detached active vector-object selection."""
        selection = self._selection.selection
        public_scene_id = self._current_public_scene_id()
        scene = self._current_scene()
        if (
            selection is None
            or public_scene_id is None
            or scene is None
            or selection.scene_id != scene.scene_id
        ):
            return None
        return selection_state(public_scene_id, selection)

    def node_selection_state(self) -> QPaneVectorNodeSelectionState | None:
        """Return the detached active vector control-point selection."""
        state = self._nodes.selection
        public_scene_id = self._current_public_scene_id()
        scene = self._current_scene()
        if (
            state is None
            or scene is None
            or public_scene_id is None
            or state.scene_id != scene.scene_id
        ):
            return None
        return QPaneVectorNodeSelectionState(
            public_scene_id,
            state.layer_id,
            state.object_id,
            state.node_index,
            state.role,
        )

    def clear_selection(self) -> bool:
        """Clear vector-object selection without changing pixel selection."""
        changed = self._selection.clear()
        self._nodes.synchronize()
        return changed

    def attach_mask(
        self,
        scene_id: uuid.UUID,
        vector_layer_id: uuid.UUID,
        target_layer_id: uuid.UUID,
        object_ids: tuple[uuid.UUID, ...],
        *,
        inverted: bool,
    ) -> bool:
        """Promote one vector layer into a target layer's editable mask effect."""
        scene_context = self._scene_context(scene_id)
        if scene_context is None:
            return False
        composition_id, resolved_scene_id = scene_context
        changed = self._masks.attach(
            composition_id,
            resolved_scene_id,
            vector_layer_id,
            target_layer_id,
            object_ids,
            inverted=inverted,
        )
        if not changed:
            return False
        self._layer_selection.select(resolved_scene_id, target_layer_id)
        if object_ids:
            self._selection.set(resolved_scene_id, target_layer_id, object_ids)
        else:
            self._selection.clear()
        self._changed()
        return True

    def clear_mask(self, scene_id: uuid.UUID, target_layer_id: uuid.UUID) -> bool:
        """Remove one vector mask effect as a chronological layer edit."""
        scene_context = self._scene_context(scene_id)
        if scene_context is None:
            return False
        composition_id, resolved_scene_id = scene_context
        changed = self._masks.clear(
            composition_id,
            resolved_scene_id,
            target_layer_id,
        )
        if changed:
            self._selection.clear()
            self._changed()
        return changed

    def mask_state(
        self,
        scene_id: uuid.UUID,
        target_layer_id: uuid.UUID,
    ) -> QPaneVectorMaskState | None:
        """Return detached state for one active layer's vector mask."""
        scene_context = self._scene_context(scene_id)
        if scene_context is None:
            return None
        composition_id, _resolved_scene_id = scene_context
        effect = self._masks.effect(composition_id, target_layer_id)
        return (
            None
            if effect is None
            else QPaneVectorMaskState(
                scene_id,
                target_layer_id,
                effect.source.vector_id,
                effect.object_ids,
                effect.transform.to_qtransform(),
                effect.inverted,
            )
        )

    def convert_to_pixel_selection(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_ids: tuple[uuid.UUID, ...] | None,
        mode: CoverageCombineMode,
    ) -> uuid.UUID | None:
        """Begin an exact semantic-alpha conversion into pixel selection."""
        context = self._context(scene_id, layer_id)
        if context is None:
            return None
        scope_id, vector_id, resolved_scene_id = context
        instance = self._compositions.layers.layer(scope_id, layer_id)
        target = self._targets.resolve(layer_id)
        if instance is None or target is None:
            return None
        selected = self._selection.selection
        effective_ids = object_ids
        if (
            effective_ids is None
            and selected is not None
            and selected.scene_id == resolved_scene_id
            and selected.layer_id == layer_id
            and selected.object_ids
        ):
            effective_ids = selected.object_ids
        return self._conversions.request_selection(
            composition_id=scope_id,
            history_scope_id=resolved_scene_id,
            public_scene_id=scene_id,
            layer_id=layer_id,
            vector_id=vector_id,
            document_to_scene=target.document_to_layer.followed_by(instance.transform),
            object_ids=None if effective_ids is None else frozenset(effective_ids),
            mode=mode,
        )

    def rasterize_layer(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        pixel_size: QSize | None,
    ) -> uuid.UUID | None:
        """Begin an atomic vector-instance conversion to editable pixels."""
        context = self._context(scene_id, layer_id)
        if context is None:
            return None
        scope_id, _vector_id, resolved_scene_id = context
        instance = self._compositions.layers.layer(scope_id, layer_id)
        if instance is None or not isinstance(
            instance.source,
            VectorDocumentReference,
        ):
            return None
        return self._conversions.request_rasterization(
            composition_id=scope_id,
            history_scope_id=resolved_scene_id,
            public_scene_id=scene_id,
            layer_id=layer_id,
            pixel_size=pixel_size,
        )

    def synchronize_selection(self) -> bool:
        """Clear object selection when its scene, layer, or objects disappeared."""
        text_changed = self._texts.synchronize()
        selection = self._selection.selection
        scene = self._current_scene()
        if selection is None:
            return self._nodes.synchronize() or text_changed
        if scene is None or selection.scene_id != scene.scene_id:
            changed = self._selection.clear()
            self._nodes.synchronize()
            return changed or text_changed
        target = self._targets.resolve(selection.layer_id)
        if target is None:
            changed = self._selection.clear()
            self._nodes.synchronize()
            return changed or text_changed
        document = self._assets.get(target.vector_id)
        if document is None or any(
            document.object(object_id) is None for object_id in selection.object_ids
        ):
            changed = self._selection.clear()
            self._nodes.synchronize()
            return changed or text_changed
        return self._nodes.synchronize() or text_changed

    def _context(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID] | None:
        """Resolve public and internal scene identities to one vector source."""
        scene = self._current_scene()
        public_scene_id = self._current_public_scene_id()
        scope_id = self._compositions.current_composition_id()
        if (
            scene is None
            or scope_id is None
            or scene_id not in {scene.scene_id, public_scene_id}
        ):
            return None
        target = self._targets.resolve(layer_id)
        if target is None:
            return None
        return scope_id, target.vector_id, scene.scene_id

    def _scene_context(
        self,
        scene_id: uuid.UUID,
    ) -> tuple[uuid.UUID, uuid.UUID] | None:
        """Resolve a public active-scene identifier into composition context."""
        scene = self._current_scene()
        public_scene_id = self._current_public_scene_id()
        scope_id = self._compositions.current_composition_id()
        if (
            scene is None
            or scope_id is None
            or scene_id not in {scene.scene_id, public_scene_id}
        ):
            return None
        return scope_id, scene.scene_id
