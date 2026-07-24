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
"""VectorApi behavior for the CuteCanvas facade."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from math import isfinite

from PySide6.QtCore import (
    QRectF,
    QSize,
)
from PySide6.QtGui import (
    QTransform,
)
from qpane.sdk.scene import LayerInteractionPolicy
from qpane.sdk.vector import (
    TextFontResolution,
    VectorParagraphStyle,
    VectorPathCommand,
    VectorShapeKind,
    VectorStyle,
    VectorTextContent,
    VectorTextStyle,
)

from cutecanvas.coverage import CoverageCombineMode
from cutecanvas.types import (
    PixelSelectionMode,
)
from cutecanvas.vector.public import (
    VectorDocumentSnapshot,
    VectorMaskSnapshot,
    VectorNodeSelectionSnapshot,
    VectorSelectionSnapshot,
    VectorTextEditSnapshot,
)


class VectorApiMixin:
    """Group vectorapi facade behavior."""

    def createVectorLayer(
        self,
        size: QSize | None = None,
        *,
        label: str = "Vector Layer",
    ) -> uuid.UUID | None:
        """Create an empty resolution-independent vector layer.

        Args:
            size: Document dimensions, or active scene dimensions when omitted.
            label: Non-empty host-facing layer label.

        Returns:
            The new layer UUID, or ``None`` when no scene is active.

        Side effects:
            Adds one movable vector layer as an undoable scene edit.
        """
        if size is not None and not isinstance(size, QSize):
            raise TypeError("size must be a QSize or None")
        if size is not None and (size.width() <= 0 or size.height() <= 0):
            raise ValueError("size dimensions must be positive")
        if not isinstance(label, str):
            raise TypeError("label must be a string")
        if not label.strip():
            raise ValueError("label must not be empty")
        editor = self._vector_editor_controller()
        return editor.create_layer(
            None if size is None else QSize(size),
            label=label,
            interaction=LayerInteractionPolicy(selectable=True, movable=True),
        )

    def vectorDocumentState(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> VectorDocumentSnapshot | None:
        """Return one vector layer's detached semantic document revision."""
        self._validate_vector_ids(scene_id, layer_id)
        return self._vector_editor_controller().document_state(scene_id, layer_id)

    def setVectorMask(
        self,
        scene_id: uuid.UUID,
        vector_layer_id: uuid.UUID,
        target_layer_id: uuid.UUID,
        object_ids: Iterable[uuid.UUID] | None = None,
        *,
        inverted: bool = False,
    ) -> bool:
        """Promote a vector layer into another layer's editable mask.

        Args:
            scene_id: Public identifier of the active scene.
            vector_layer_id: Vector layer whose document becomes the mask source.
            target_layer_id: Layer instance clipped by the vector geometry.
            object_ids: Exact mask objects, or every object when omitted.
            inverted: Whether geometry hides rather than reveals target content.

        Returns:
            True when one atomic layer-stack transition was recorded.

        Side effects:
            Removes the vector layer instance, selects the target, and retains the
            semantic document as its editable effect source.
        """
        self._validate_vector_ids(scene_id, vector_layer_id, target_layer_id)
        values = () if object_ids is None else tuple(object_ids)
        if any(not isinstance(object_id, uuid.UUID) for object_id in values):
            raise TypeError("object_ids must contain UUID values")
        if not isinstance(inverted, bool):
            raise TypeError("inverted must be a bool")
        return self._vector_editor_controller().attach_mask(
            scene_id,
            vector_layer_id,
            target_layer_id,
            values,
            inverted=inverted,
        )

    def vectorMaskState(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> VectorMaskSnapshot | None:
        """Return detached semantic vector-mask state for one layer."""
        self._validate_vector_ids(scene_id, layer_id)
        return self._vector_editor_controller().mask_state(scene_id, layer_id)

    def clearVectorMask(self, scene_id: uuid.UUID, layer_id: uuid.UUID) -> bool:
        """Remove one layer's vector mask through composition chronology."""
        self._validate_vector_ids(scene_id, layer_id)
        return self._vector_editor_controller().clear_mask(scene_id, layer_id)

    def addVectorShape(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        shape: VectorShapeKind,
        bounds: QRectF,
        style: VectorStyle | None = None,
    ) -> uuid.UUID | None:
        """Add one editable parametric rectangle or ellipse."""
        self._validate_vector_ids(scene_id, layer_id)
        if not isinstance(shape, VectorShapeKind):
            raise TypeError("shape must be VectorShapeKind")
        if not isinstance(bounds, QRectF):
            raise TypeError("bounds must be a QRectF")
        if (
            not all(
                isfinite(value)
                for value in (bounds.x(), bounds.y(), bounds.width(), bounds.height())
            )
            or bounds.width() < 0.0
            or bounds.height() < 0.0
        ):
            raise ValueError("bounds must be finite with non-negative dimensions")
        if style is not None and not isinstance(style, VectorStyle):
            raise TypeError("style must be VectorStyle or None")
        return self._vector_editor_controller().add_shape(
            scene_id,
            layer_id,
            shape,
            QRectF(bounds),
            style or VectorStyle(),
        )

    def addVectorPath(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        commands: Iterable[VectorPathCommand],
        style: VectorStyle | None = None,
    ) -> uuid.UUID | None:
        """Add one durable command-based vector path."""
        self._validate_vector_ids(scene_id, layer_id)
        command_values = tuple(commands)
        if any(
            not isinstance(command, VectorPathCommand) for command in command_values
        ):
            raise TypeError("commands must contain VectorPathCommand values")
        if not command_values:
            raise ValueError("commands must not be empty")
        if style is not None and not isinstance(style, VectorStyle):
            raise TypeError("style must be VectorStyle or None")
        return self._vector_editor_controller().add_path(
            scene_id,
            layer_id,
            command_values,
            style or VectorStyle(),
        )

    def addVectorText(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        bounds: QRectF,
        content: VectorTextContent,
    ) -> uuid.UUID | None:
        """Add editable semantic Unicode text inside a layout box."""
        self._validate_vector_ids(scene_id, layer_id)
        if not isinstance(bounds, QRectF):
            raise TypeError("bounds must be a QRectF")
        if bounds.isEmpty() or not all(
            isfinite(value)
            for value in (bounds.x(), bounds.y(), bounds.width(), bounds.height())
        ):
            raise ValueError("bounds must be finite and non-empty")
        if not isinstance(content, VectorTextContent):
            raise TypeError("content must be VectorTextContent")
        return self._vector_editor_controller().add_text(
            scene_id, layer_id, QRectF(bounds), content
        )

    def updateVectorText(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_id: uuid.UUID,
        *,
        bounds: QRectF | None = None,
        content: VectorTextContent | None = None,
    ) -> bool:
        """Atomically replace semantic text content or its layout box."""
        self._validate_vector_ids(scene_id, layer_id, object_id)
        if bounds is not None and not isinstance(bounds, QRectF):
            raise TypeError("bounds must be a QRectF or None")
        if bounds is not None and (
            bounds.isEmpty()
            or not all(
                isfinite(value)
                for value in (bounds.x(), bounds.y(), bounds.width(), bounds.height())
            )
        ):
            raise ValueError("bounds must be finite and non-empty")
        if content is not None and not isinstance(content, VectorTextContent):
            raise TypeError("content must be VectorTextContent or None")
        if bounds is None and content is None:
            return False
        return self._vector_editor_controller().update_text(
            scene_id,
            layer_id,
            object_id,
            bounds=None if bounds is None else QRectF(bounds),
            content=content,
        )

    def beginVectorTextEdit(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_id: uuid.UUID,
    ) -> bool:
        """Begin in-place editing of one semantic text object."""
        self._validate_vector_ids(scene_id, layer_id, object_id)
        return self._vector_editor_controller().begin_text_edit(
            scene_id, layer_id, object_id
        )

    def vectorTextEditState(self) -> VectorTextEditSnapshot | None:
        """Return the active in-place semantic text session."""
        return self._vector_editor_controller().text_edit_state()

    def commitVectorTextEdit(self) -> bool:
        """Commit the active text session as one history transition."""
        return self._vector_text_controller().commit()

    def cancelVectorTextEdit(self) -> bool:
        """Discard the active text session without changing history."""
        return self._vector_text_controller().cancel()

    def vectorTextStyle(self) -> VectorTextStyle:
        """Return the current semantic text creation style."""
        return self._vector_text_controller().style

    def setVectorTextStyle(self, style: VectorTextStyle) -> bool:
        """Set the current text style and apply it to active text."""
        if not isinstance(style, VectorTextStyle):
            raise TypeError("style must be VectorTextStyle")
        return self._vector_text_controller().set_style(style)

    def vectorParagraphStyle(self) -> VectorParagraphStyle:
        """Return the current semantic paragraph policy."""
        return self._vector_text_controller().paragraph

    def setVectorParagraphStyle(self, style: VectorParagraphStyle) -> bool:
        """Set paragraph policy and apply it to active text."""
        if not isinstance(style, VectorParagraphStyle):
            raise TypeError("style must be VectorParagraphStyle")
        return self._vector_text_controller().set_paragraph(style)

    def vectorTextFontResolutions(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_id: uuid.UUID,
    ) -> tuple[TextFontResolution, ...]:
        """Return requested-to-resolved font diagnostics for one text object."""
        self._validate_vector_ids(scene_id, layer_id, object_id)
        return self._vector_editor_controller().text_font_resolutions(
            scene_id, layer_id, object_id
        )

    def convertVectorTextToPaths(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_id: uuid.UUID,
    ) -> uuid.UUID | None:
        """Begin conversion of semantic text to color-preserving glyph paths.

        Side effects:
            Emits ``vectorRequestCompleted`` exactly once for accepted work.
        """
        self._validate_vector_ids(scene_id, layer_id, object_id)
        return self._vector_editor_controller().convert_text_to_paths(
            scene_id, layer_id, object_id
        )

    def updateVectorObject(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_id: uuid.UUID,
        *,
        transform: QTransform | None = None,
        style: VectorStyle | None = None,
    ) -> bool:
        """Atomically update one stable vector object's transform or style."""
        self._validate_vector_ids(scene_id, layer_id, object_id)
        if transform is not None and not isinstance(transform, QTransform):
            raise TypeError("transform must be a QTransform or None")
        if style is not None and not isinstance(style, VectorStyle):
            raise TypeError("style must be VectorStyle or None")
        if transform is None and style is None:
            return False
        return self._vector_editor_controller().update_object(
            scene_id,
            layer_id,
            object_id,
            transform=None if transform is None else QTransform(transform),
            style=style,
        )

    def removeVectorObject(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_id: uuid.UUID,
    ) -> bool:
        """Remove one stable vector object through composition chronology."""
        self._validate_vector_ids(scene_id, layer_id, object_id)
        return self._vector_editor_controller().remove_object(
            scene_id,
            layer_id,
            object_id,
        )

    def reorderVectorObject(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_id: uuid.UUID,
        index: int,
    ) -> bool:
        """Move one vector object to a clamped document order index."""
        self._validate_vector_ids(scene_id, layer_id, object_id)
        if not isinstance(index, int):
            raise TypeError("index must be an int")
        return self._vector_editor_controller().reorder_object(
            scene_id,
            layer_id,
            object_id,
            index,
        )

    def vectorSelectionState(self) -> VectorSelectionSnapshot | None:
        """Return vector-object selection independently of pixel selection."""
        return self._vector_editor_controller().selection_state()

    def vectorNodeSelectionState(self) -> VectorNodeSelectionSnapshot | None:
        """Return the selected vector control point, independent of pixel selection."""
        return self._vector_editor_controller().node_selection_state()

    def setSelectedVectorObjects(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_ids: Iterable[uuid.UUID],
    ) -> bool:
        """Select existing objects within one active vector layer."""
        self._validate_vector_ids(scene_id, layer_id)
        values = tuple(object_ids)
        if any(not isinstance(object_id, uuid.UUID) for object_id in values):
            raise TypeError("object_ids must contain UUID values")
        return self._vector_editor_controller().set_selection(
            scene_id,
            layer_id,
            values,
        )

    def clearVectorSelection(self) -> bool:
        """Clear vector-object selection without changing pixel selection."""
        return self._vector_editor_controller().clear_selection()

    def vectorToolShape(self) -> VectorShapeKind:
        """Return the active parametric kind used by the vector shape tool."""
        return self._vector_interaction_controller().shape

    def setVectorToolShape(self, shape: VectorShapeKind) -> bool:
        """Select the parametric kind used by future shape-tool gestures."""
        if not isinstance(shape, VectorShapeKind):
            raise TypeError("shape must be VectorShapeKind")
        return self._vector_interaction_controller().set_shape(shape)

    def vectorToolStyle(self) -> VectorStyle:
        """Return the immutable style used by future vector objects."""
        return self._vector_interaction_controller().style

    def setVectorToolStyle(self, style: VectorStyle) -> bool:
        """Replace the style used by future shape and path gestures."""
        if not isinstance(style, VectorStyle):
            raise TypeError("style must be VectorStyle")
        return self._vector_interaction_controller().set_style(style)

    def convertVectorToPixelSelection(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_ids: Iterable[uuid.UUID] | None = None,
        mode: PixelSelectionMode = PixelSelectionMode.REPLACE,
    ) -> uuid.UUID | None:
        """Begin conversion of vector appearance into pixel selection.

        Args:
            scene_id: Public identifier of the active scene.
            layer_id: Vector layer containing the source objects.
            object_ids: Exact objects, the active object selection, or all objects.
            mode: Pixel-selection replacement or composition behavior.

        Returns:
            A request UUID, or ``None`` when the layer is not current vector content.

        Side effects:
            Emits ``vectorRequestCompleted`` exactly once for accepted work.
        """
        self._validate_vector_ids(scene_id, layer_id)
        if object_ids is None:
            values = None
        else:
            values = tuple(object_ids)
            if any(not isinstance(object_id, uuid.UUID) for object_id in values):
                raise TypeError("object_ids must contain UUID values")
        if not isinstance(mode, PixelSelectionMode):
            raise TypeError("mode must be PixelSelectionMode")
        if not self._anchor_floating_pixels_before_edit():
            return None
        return self._vector_editor_controller().convert_to_pixel_selection(
            scene_id,
            layer_id,
            values,
            CoverageCombineMode(mode.value),
        )
