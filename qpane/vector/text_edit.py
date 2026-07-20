#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Durable-base in-place editing sessions for semantic vector text."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace

from PySide6.QtCore import QLineF, QPointF, QRectF
from PySide6.QtGui import QPolygonF

from ..scene.affine import LayerTransform
from ..scene.layer_selection import SceneLayerSelectionController
from .editing import VectorEditService
from .model import VectorDocument, VectorObject
from .projection import VectorDocumentProjection
from .public import (
    QPaneTextFontResolution,
    QPaneVectorTextEditState,
    VectorObjectKind,
    VectorParagraphStyle,
    VectorStyle,
    VectorTextContent,
    VectorTextSpan,
    VectorTextStyle,
)
from .selection import VectorObjectSelectionController
from .store import VectorAssetStore
from .targets import VectorAuthoringTarget, VectorAuthoringTargetResolver
from .text_layout import SemanticTextLayoutCache, text_caret_rect

_DEFAULT_TEXT_BOX_WIDTH = 360.0
_DEFAULT_TEXT_BOX_HEIGHT = 180.0


@dataclass(frozen=True, slots=True)
class VectorTextOverlayState:
    """Carry detached panel-space text-box and caret feedback."""

    box: QPolygonF
    caret: QLineF

    def __post_init__(self) -> None:
        """Detach mutable Qt geometry from the session owner."""
        object.__setattr__(self, "box", QPolygonF(self.box))
        object.__setattr__(self, "caret", QLineF(self.caret))


@dataclass(slots=True)
class _VectorTextSession:
    """Retain one exact durable base and current semantic preview."""

    target: VectorAuthoringTarget
    base: VectorDocument
    item: VectorObject
    cursor: int
    is_new: bool
    caret_rect: QRectF


class VectorTextEditController:
    """Own semantic text options, transient editing, and atomic resolution."""

    def __init__(
        self,
        *,
        assets: VectorAssetStore,
        edits: VectorEditService,
        projection: VectorDocumentProjection,
        targets: VectorAuthoringTargetResolver,
        layer_selection: SceneLayerSelectionController,
        object_selection: VectorObjectSelectionController,
        layouts: SemanticTextLayoutCache,
        changed: Callable[[], None],
        state_changed: Callable[[], None],
        options_changed: Callable[[], None],
    ) -> None:
        """Bind document, coordinate, selection, layout, and publication owners."""
        self._assets = assets
        self._edits = edits
        self._projection = projection
        self._targets = targets
        self._layer_selection = layer_selection
        self._object_selection = object_selection
        self._layouts = layouts
        self._changed = changed
        self._state_changed = state_changed
        self._options_changed = options_changed
        self._style = VectorTextStyle()
        self._paragraph = VectorParagraphStyle()
        self._session: _VectorTextSession | None = None

    @property
    def style(self) -> VectorTextStyle:
        """Return the current creation/editing character style."""
        return self._style

    @property
    def paragraph(self) -> VectorParagraphStyle:
        """Return the current creation/editing paragraph style."""
        return self._paragraph

    @property
    def active(self) -> bool:
        """Return whether an unresolved in-place session exists."""
        return self._session is not None

    def set_style(self, style: VectorTextStyle) -> bool:
        """Set creation style and apply it to the active whole text object."""
        normalized = VectorTextStyle(
            style.families,
            style.font_size,
            style.weight,
            style.italic,
            style.letter_spacing,
            style.color,
        )
        changed = normalized != self._style
        self._style = normalized
        session = self._session
        if session is not None and session.item.text is not None:
            self._discard_session_layout(session)
            content = replace(session.item.text, style=normalized, spans=())
            session.item = replace(session.item, text=content)
            self._refresh_caret(session)
            self._publish_preview(session)
            changed = True
        if changed:
            self._options_changed()
        return changed

    def set_paragraph(self, style: VectorParagraphStyle) -> bool:
        """Set paragraph policy and apply it to the active text object."""
        normalized = VectorParagraphStyle(
            style.alignment,
            style.direction,
            style.line_height,
        )
        changed = normalized != self._paragraph
        self._paragraph = normalized
        session = self._session
        if session is not None and session.item.text is not None:
            self._discard_session_layout(session)
            session.item = replace(
                session.item,
                text=replace(session.item.text, paragraph=normalized),
            )
            self._refresh_caret(session)
            self._publish_preview(session)
            changed = True
        if changed:
            self._options_changed()
        return changed

    def begin_at(self, panel_point: QPointF) -> bool:
        """Edit the topmost text at a panel point or start a new text box."""
        target = self._active_target()
        if target is None:
            return False
        point = self._targets.panel_to_document(target, panel_point)
        document = self._assets.get(target.vector_id)
        if point is None or document is None:
            return False
        item = next(
            (
                candidate
                for candidate in reversed(document.objects)
                if candidate.kind is VectorObjectKind.TEXT
                and _text_box_contains(candidate, point)
            ),
            None,
        )
        if item is not None:
            return self._begin(target, document, item, is_new=False)
        bounds = QRectF(
            point.x(),
            point.y(),
            min(_DEFAULT_TEXT_BOX_WIDTH, max(1.0, document.bounds.right - point.x())),
            min(
                _DEFAULT_TEXT_BOX_HEIGHT,
                max(1.0, document.bounds.bottom - point.y()),
            ),
        )
        item = VectorObject(
            uuid.uuid4(),
            VectorObjectKind.TEXT,
            (bounds.x(), bounds.y(), bounds.width(), bounds.height()),
            LayerTransform(),
            VectorStyle(fill=None, stroke=None, stroke_width=0.0),
            text=VectorTextContent("", self._style, (), self._paragraph),
        )
        return self._begin(target, document, item, is_new=True)

    def begin_object(self, layer_id: uuid.UUID, object_id: uuid.UUID) -> bool:
        """Begin editing one text object in the current composition."""
        target = self._targets.resolve(layer_id)
        document = None if target is None else self._assets.get(target.vector_id)
        item = None if document is None else document.object(object_id)
        if (
            target is None
            or document is None
            or item is None
            or item.kind is not VectorObjectKind.TEXT
        ):
            return False
        self._layer_selection.select(target.scene_id, target.layer_id)
        return self._begin(target, document, item, is_new=False)

    def insert(self, value: str) -> bool:
        """Insert arbitrary Unicode text at the active Python-codepoint cursor."""
        if not value or self._session is None:
            return False
        return self._replace_range(self._session.cursor, self._session.cursor, value)

    def backspace(self) -> bool:
        """Remove the codepoint before the active cursor."""
        session = self._session
        if session is None or session.cursor <= 0:
            return False
        return self._replace_range(session.cursor - 1, session.cursor, "")

    def delete(self) -> bool:
        """Remove the codepoint after the active cursor."""
        session = self._session
        text = None if session is None else session.item.text
        if session is None or text is None or session.cursor >= len(text.text):
            return False
        return self._replace_range(session.cursor, session.cursor + 1, "")

    def move_cursor(self, offset: int) -> bool:
        """Move the cursor by a signed Python-codepoint offset."""
        session = self._session
        if session is None or session.item.text is None:
            return False
        cursor = max(0, min(len(session.item.text.text), session.cursor + int(offset)))
        if cursor == session.cursor:
            return False
        session.cursor = cursor
        self._refresh_caret(session)
        self._state_changed()
        self._changed()
        return True

    def move_cursor_to(self, cursor: int) -> bool:
        """Move the cursor to a clamped absolute codepoint boundary."""
        session = self._session
        if session is None or session.item.text is None:
            return False
        resolved = max(0, min(len(session.item.text.text), int(cursor)))
        if resolved == session.cursor:
            return False
        session.cursor = resolved
        self._refresh_caret(session)
        self._state_changed()
        self._changed()
        return True

    def commit(self) -> bool:
        """Resolve the whole in-place session as at most one history command."""
        session = self._session
        if session is None:
            return False
        after = self._preview_document(session)
        self._session = None
        self._projection.clear(session.target.vector_id)
        content = session.item.text
        if session.is_new and (content is None or not content.text):
            self._state_changed()
            self._changed()
            return True
        committed = self._edits.commit_document(
            session.target.scene_id,
            session.target.layer_id,
            session.base,
            after,
        )
        self._state_changed()
        self._changed()
        return committed

    def cancel(self) -> bool:
        """Discard the transient session without changing durable history."""
        session = self._session
        if session is None:
            return False
        self._session = None
        self._projection.clear(session.target.vector_id)
        self._state_changed()
        self._changed()
        return True

    def state(self) -> QPaneVectorTextEditState | None:
        """Return one detached active text-edit state."""
        session = self._session
        content = None if session is None else session.item.text
        return (
            None
            if session is None or content is None
            else QPaneVectorTextEditState(
                session.target.scene_id,
                session.target.layer_id,
                session.item.object_id,
                content.text,
                session.cursor,
                session.is_new,
            )
        )

    def overlay_state(self) -> VectorTextOverlayState | None:
        """Return exact panel-space box and shaped caret geometry."""
        session = self._session
        content = None if session is None else session.item.text
        if session is None or content is None:
            return None
        transform = self._targets.document_to_panel_transform(session.target)
        if transform is None:
            return None
        object_transform = session.item.transform.to_qtransform()
        text_to_panel = object_transform * transform
        bounds = QRectF(*session.item.local_bounds)
        corners = QPolygonF(
            (
                text_to_panel.map(bounds.topLeft()),
                text_to_panel.map(bounds.topRight()),
                text_to_panel.map(bounds.bottomRight()),
                text_to_panel.map(bounds.bottomLeft()),
            )
        )
        caret_rect = session.caret_rect
        caret = QLineF(
            text_to_panel.map(caret_rect.topLeft()),
            text_to_panel.map(caret_rect.bottomLeft()),
        )
        return VectorTextOverlayState(corners, caret)

    def font_resolutions(
        self,
        layer_id: uuid.UUID,
        object_id: uuid.UUID,
    ) -> tuple[QPaneTextFontResolution, ...]:
        """Return requested-to-resolved font diagnostics for one text object."""
        target = self._targets.resolve(layer_id)
        document = None if target is None else self._assets.get(target.vector_id)
        item = None if document is None else document.object(object_id)
        if item is None or item.kind is not VectorObjectKind.TEXT or item.text is None:
            return ()
        return self._layouts.product(
            item.text, QRectF(*item.local_bounds)
        ).font_resolutions

    def synchronize(self) -> bool:
        """Cancel a session whose target or durable base changed externally."""
        session = self._session
        if session is None or self._session_current(session):
            return False
        return self.cancel()

    def _begin(
        self,
        target: VectorAuthoringTarget,
        document: VectorDocument,
        item: VectorObject,
        *,
        is_new: bool,
    ) -> bool:
        """Install one exact session and publish its initial preview."""
        if self._session is not None:
            self.commit()
            document = self._assets.get(target.vector_id) or document
        cursor = 0 if is_new or item.text is None else len(item.text.text)
        content = item.text
        bounds = QRectF(*item.local_bounds)
        caret_rect = (
            QRectF(bounds.x(), bounds.y(), 1.0, self._style.font_size)
            if content is None
            else text_caret_rect(content, bounds, cursor)
        )
        self._session = _VectorTextSession(
            target,
            document,
            item,
            cursor,
            is_new,
            caret_rect,
        )
        self._style = item.text.style if item.text is not None else self._style
        self._paragraph = (
            item.text.paragraph if item.text is not None else self._paragraph
        )
        self._object_selection.set(target.scene_id, target.layer_id, (item.object_id,))
        self._publish_preview(self._session)
        self._options_changed()
        self._state_changed()
        return True

    def _replace_range(self, start: int, end: int, value: str) -> bool:
        """Replace one codepoint range while preserving surrounding span styles."""
        session = self._session
        content = None if session is None else session.item.text
        if session is None or content is None:
            return False
        updated = _replace_content(content, start, end, value)
        if updated == content:
            return False
        self._discard_session_layout(session)
        session.item = replace(session.item, text=updated)
        session.cursor = start + len(value)
        self._refresh_caret(session)
        self._publish_preview(session)
        self._state_changed()
        return True

    def _publish_preview(self, session: _VectorTextSession) -> None:
        """Publish the current session through the sole vector projection owner."""
        if self._projection.set_document_preview(
            session.target.vector_id,
            self._preview_document(session),
            session.item.object_id,
        ):
            self._changed()

    @staticmethod
    def _preview_document(session: _VectorTextSession) -> VectorDocument:
        """Return the immutable semantic document represented by one session."""
        return (
            session.base.add(session.item)
            if session.is_new
            else session.base.replace_object(session.item)
        )

    def _active_target(self) -> VectorAuthoringTarget | None:
        """Resolve the selected direct vector layer or vector-mask target."""
        selection = self._layer_selection.current
        return None if selection is None else self._targets.resolve(selection.layer_id)

    def _session_current(self, session: _VectorTextSession) -> bool:
        """Return whether target and durable document still match the session base."""
        target = self._targets.resolve(session.target.layer_id)
        return bool(
            target == session.target
            and self._assets.get(session.target.vector_id) == session.base
        )

    def _discard_session_layout(self, session: _VectorTextSession) -> None:
        """Release derivatives for the transient revision being replaced."""
        content = session.item.text
        if content is not None:
            self._layouts.discard(content, QRectF(*session.item.local_bounds))

    @staticmethod
    def _refresh_caret(session: _VectorTextSession) -> None:
        """Refresh the session-owned local caret after semantic changes."""
        content = session.item.text
        if content is not None:
            session.caret_rect = text_caret_rect(
                content,
                QRectF(*session.item.local_bounds),
                session.cursor,
            )


def _replace_content(
    content: VectorTextContent,
    start: int,
    end: int,
    value: str,
) -> VectorTextContent:
    """Replace text and retain exact per-codepoint styles around the mutation."""
    start = max(0, min(len(content.text), int(start)))
    end = max(start, min(len(content.text), int(end)))
    styles: list[VectorTextStyle] = [content.style] * len(content.text)
    for span in content.spans:
        styles[span.start : span.start + span.length] = [span.style] * span.length
    inherited = (
        styles[start - 1]
        if start > 0
        else (styles[start] if start < len(styles) else content.style)
    )
    new_styles = [*styles[:start], *([inherited] * len(value)), *styles[end:]]
    text = content.text[:start] + value + content.text[end:]
    spans = _compress_spans(new_styles, content.style)
    return VectorTextContent(text, content.style, spans, content.paragraph)


def _text_box_contains(item: VectorObject, point: QPointF) -> bool:
    """Return whether a document point lies inside a transformed text box."""
    inverse, invertible = item.transform.to_qtransform().inverted()
    return bool(
        invertible and QRectF(*item.local_bounds).contains(inverse.map(QPointF(point)))
    )


def _compress_spans(
    styles: list[VectorTextStyle],
    default: VectorTextStyle,
) -> tuple[VectorTextSpan, ...]:
    """Compress per-codepoint styles back into ordered semantic ranges."""
    spans: list[VectorTextSpan] = []
    index = 0
    while index < len(styles):
        style = styles[index]
        end = index + 1
        while end < len(styles) and styles[end] == style:
            end += 1
        if style != default:
            spans.append(VectorTextSpan(index, end - index, style))
        index = end
    return tuple(spans)
