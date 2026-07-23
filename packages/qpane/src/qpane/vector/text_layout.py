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
"""Qt shaping adapter and byte-bounded derivatives for semantic vector text."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Hashable
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontInfo,
    QPainter,
    QPainterPath,
    QPicture,
    QTextCharFormat,
    QTextLayout,
    QTextLine,
    QTextOption,
    QTransform,
)

from .public import (
    TextFontResolution,
    VectorParagraphStyle,
    VectorTextAlignment,
    VectorTextContent,
    VectorTextDirection,
    VectorTextStyle,
)


@dataclass(frozen=True, slots=True)
class TextLayoutProduct:
    """Carry immutable shaped drawing, outline, diagnostics, and cache weight."""

    picture: QPicture
    outline: QPainterPath
    painted_outlines: tuple[tuple[QColor, QPainterPath], ...]
    font_resolutions: tuple[TextFontResolution, ...]
    cursor_rects: tuple[QRectF, ...]
    retained_bytes: int


class SemanticTextLayoutCache:
    """Own Qt-shaped semantic text products under a coordinated byte ceiling."""

    def __init__(self, budget_bytes: int = 8 * 1024 * 1024) -> None:
        """Initialize an empty least-recently-used layout cache."""
        self._budget_bytes = max(0, int(budget_bytes))
        self._usage_bytes = 0
        self._entries: OrderedDict[Hashable, TextLayoutProduct] = OrderedDict()
        self._usage_changed: Callable[[int], None] | None = None

    @property
    def usage_bytes(self) -> int:
        """Return estimated retained picture and outline bytes."""
        return self._usage_bytes

    @property
    def entry_count(self) -> int:
        """Return the number of retained shaped layouts."""
        return len(self._entries)

    def set_usage_changed(self, callback: Callable[[int], None] | None) -> None:
        """Install shared-cache usage publication."""
        self._usage_changed = callback

    def set_budget(self, budget_bytes: int) -> None:
        """Apply a strict cache budget and trim immediately."""
        self._budget_bytes = max(0, int(budget_bytes))
        self.trim_to(self._budget_bytes)

    def trim_to(self, target_bytes: int) -> None:
        """Evict oldest products until usage meets ``target_bytes``."""
        target = max(0, int(target_bytes))
        while self._entries and self._usage_bytes > target:
            _key, product = self._entries.popitem(last=False)
            self._usage_bytes -= product.retained_bytes
        self._report()

    def discard(self, content: VectorTextContent, bounds: QRectF) -> None:
        """Release every derivative for one obsolete semantic layout revision."""
        layout_key = _layout_key(content, bounds)
        for key in tuple(self._entries):
            if key[0] != layout_key:
                continue
            product = self._entries.pop(key)
            self._usage_bytes -= product.retained_bytes
        self._report()

    def product(
        self,
        content: VectorTextContent,
        bounds: QRectF,
    ) -> TextLayoutProduct:
        """Return or shape one exact semantic content and text-box pair."""
        return self._product(
            content,
            bounds,
            include_picture=True,
            include_outline=True,
            include_painted=True,
            include_carets=True,
            include_diagnostics=True,
        )

    def picture_product(
        self,
        content: VectorTextContent,
        bounds: QRectF,
    ) -> TextLayoutProduct:
        """Return a presentation-only product without geometry or caret work."""
        return self._product(
            content,
            bounds,
            include_picture=True,
            include_outline=False,
            include_painted=False,
            include_carets=False,
            include_diagnostics=False,
        )

    def outline_product(
        self,
        content: VectorTextContent,
        bounds: QRectF,
    ) -> TextLayoutProduct:
        """Return only aggregate painted geometry for hit testing."""
        return self._product(
            content,
            bounds,
            include_picture=False,
            include_outline=True,
            include_painted=False,
            include_carets=False,
            include_diagnostics=False,
        )

    def painted_outline_product(
        self,
        content: VectorTextContent,
        bounds: QRectF,
    ) -> TextLayoutProduct:
        """Return only color-grouped exact outlines for durable conversion."""
        return self._product(
            content,
            bounds,
            include_picture=False,
            include_outline=False,
            include_painted=True,
            include_carets=False,
            include_diagnostics=False,
        )

    def _product(
        self,
        content: VectorTextContent,
        bounds: QRectF,
        *,
        include_picture: bool,
        include_outline: bool,
        include_painted: bool,
        include_carets: bool,
        include_diagnostics: bool,
    ) -> TextLayoutProduct:
        """Return one cached product for the requested derivative breadth."""
        key = (
            _layout_key(content, bounds),
            include_picture,
            include_outline,
            include_painted,
            include_carets,
            include_diagnostics,
        )
        product = self._entries.pop(key, None)
        if product is not None:
            self._entries[key] = product
            return product
        product = shape_text(
            content,
            bounds,
            include_picture=include_picture,
            include_outline=include_outline,
            include_painted=include_painted,
            include_carets=include_carets,
            include_diagnostics=include_diagnostics,
        )
        if product.retained_bytes <= self._budget_bytes:
            self._entries[key] = product
            self._usage_bytes += product.retained_bytes
            self.trim_to(self._budget_bytes)
        return product

    def _report(self) -> None:
        """Publish exact retained usage after mutations."""
        if self._usage_changed is not None:
            self._usage_changed(self._usage_bytes)


def shape_text(
    content: VectorTextContent,
    bounds: QRectF,
    *,
    include_picture: bool = True,
    include_outline: bool = True,
    include_painted: bool = True,
    include_carets: bool = True,
    include_diagnostics: bool = True,
) -> TextLayoutProduct:
    """Shape Unicode semantic text through Qt without retaining layout authority."""
    picture = QPicture()
    outline = QPainterPath()
    painted_paths: dict[int, tuple[QColor, QPainterPath]] | None = (
        {} if include_outline or include_painted else None
    )
    resolutions = _font_resolutions(content) if include_diagnostics else ()
    painter = QPainter(picture) if include_picture else None
    try:
        if painter is not None:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setClipRect(bounds)
        cursor_rects = _shape_paragraphs(
            content,
            bounds,
            painter,
            painted_paths,
            include_carets=include_carets,
        )
    finally:
        if painter is not None:
            painter.end()
    if include_outline and painted_paths is not None:
        for _color, painted_path in painted_paths.values():
            outline.addPath(painted_path)
    clip = QPainterPath()
    clip.addRect(bounds)
    clipped_outline = outline.intersected(clip) if include_outline else outline
    painted_outlines = (
        tuple(
            (QColor(color), path.intersected(clip))
            for color, path in painted_paths.values()
        )
        if include_painted and painted_paths is not None
        else ()
    )
    retained = max(
        256,
        (int(picture.size()) if include_picture else 0)
        + clipped_outline.elementCount() * 32
        + sum(path.elementCount() * 32 for _color, path in painted_outlines),
    )
    return TextLayoutProduct(
        picture,
        clipped_outline,
        painted_outlines,
        resolutions,
        cursor_rects,
        retained,
    )


def draw_semantic_text(
    painter: QPainter,
    content: VectorTextContent,
    bounds: QRectF,
) -> None:
    """Draw presentation-only text directly into an existing picture or frame."""
    painter.save()
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setClipRect(bounds)
        _shape_paragraphs(
            content,
            bounds,
            painter,
            None,
            include_carets=False,
        )
    finally:
        painter.restore()


def text_caret_rect(
    content: VectorTextContent,
    bounds: QRectF,
    cursor: int,
) -> QRectF:
    """Shape only the paragraph work needed for one codepoint caret."""
    resolved_cursor = max(0, min(len(content.text), int(cursor)))
    paragraphs = content.text.split("\n")
    character_offset = 0
    y_offset = bounds.y()
    for index, paragraph in enumerate(paragraphs):
        paragraph_end = character_offset + len(paragraph)
        layout = _layout_paragraph(content, paragraph, character_offset, bounds.width())
        if resolved_cursor <= paragraph_end:
            local_cursor = resolved_cursor - character_offset
            qt_cursor = _utf16_length(paragraph[:local_cursor])
            line = _line_for_cursor(layout, qt_cursor)
            if line is None:
                return QRectF(bounds.x(), y_offset, 1.0, content.style.font_size)
            x, _resolved = line.cursorToX(qt_cursor)
            return QRectF(
                bounds.x() + x,
                y_offset + line.y(),
                1.0,
                line.height(),
            )
        y_offset += _layout_height(content, layout)
        character_offset = paragraph_end + (1 if index < len(paragraphs) - 1 else 0)
    return QRectF(bounds.x(), y_offset, 1.0, content.style.font_size)


def _shape_paragraphs(
    content: VectorTextContent,
    bounds: QRectF,
    painter: QPainter | None,
    painted: dict[int, tuple[QColor, QPainterPath]] | None,
    *,
    include_carets: bool,
) -> tuple[QRectF, ...]:
    """Lay out newline-separated paragraphs and collect their exact glyph paths."""
    paragraphs = content.text.split("\n")
    character_offset = 0
    y_offset = bounds.y()
    cursor_rects = (
        [QRectF(bounds.x(), bounds.y(), 1.0, content.style.font_size)]
        * (len(content.text) + 1)
        if include_carets
        else []
    )
    for index, paragraph in enumerate(paragraphs):
        layout = _layout_paragraph(content, paragraph, character_offset, bounds.width())
        if painter is not None:
            painter.setPen(content.style.color)
            layout.draw(painter, QPointF(bounds.x(), y_offset))
        if painted is not None:
            for start, length, style in _paragraph_style_runs(
                content, character_offset, len(paragraph)
            ):
                if style.color.alpha() <= 0:
                    continue
                key = style.color.rgba()
                color, color_path = painted.setdefault(
                    key, (QColor(style.color), QPainterPath())
                )
                del color
                utf16_start = _utf16_length(paragraph[:start])
                utf16_length = _utf16_length(paragraph[start : start + length])
                _append_glyph_outlines(
                    layout,
                    color_path,
                    bounds.x(),
                    y_offset,
                    start=utf16_start,
                    length=utf16_length,
                )
        if include_carets:
            _place_cursor_rects(
                layout,
                paragraph,
                character_offset,
                bounds.x(),
                y_offset,
                cursor_rects,
            )
        y_offset += _layout_height(content, layout)
        character_offset += len(paragraph)
        if index < len(paragraphs) - 1:
            character_offset += 1
    return tuple(QRectF(rect) for rect in cursor_rects) if include_carets else ()


def _layout_paragraph(
    content: VectorTextContent,
    paragraph: str,
    character_offset: int,
    width: float,
) -> QTextLayout:
    """Create one fully positioned Qt paragraph layout."""
    layout = QTextLayout(paragraph, _font(content.style))
    layout.setTextOption(_text_option(content.paragraph))
    layout.setFormats(_paragraph_formats(content, character_offset, len(paragraph)))
    layout.beginLayout()
    line_count = 0
    while True:
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(max(1.0, width))
        natural_height = line.height()
        line.setPosition(
            QPointF(
                0.0,
                line_count * natural_height * content.paragraph.line_height,
            )
        )
        line_count += 1
    layout.endLayout()
    return layout


def _layout_height(content: VectorTextContent, layout: QTextLayout) -> float:
    """Return one paragraph's line-height-adjusted block height."""
    return max(
        _font(content.style).pixelSize() * content.paragraph.line_height,
        sum(
            layout.lineAt(index).height() * content.paragraph.line_height
            for index in range(layout.lineCount())
        ),
    )


def _place_cursor_rects(
    layout: QTextLayout,
    paragraph: str,
    character_offset: int,
    x_offset: float,
    y_offset: float,
    cursor_rects: list[QRectF],
) -> None:
    """Record shaped caret geometry for every Python-codepoint boundary."""
    qt_cursor = 0
    for local_cursor in range(len(paragraph) + 1):
        line = _line_for_cursor(layout, qt_cursor)
        if line is None:
            pass
        else:
            x, _resolved = line.cursorToX(qt_cursor)
            cursor_rects[character_offset + local_cursor] = QRectF(
                x_offset + x,
                y_offset + line.y(),
                1.0,
                line.height(),
            )
        if local_cursor < len(paragraph):
            qt_cursor += 2 if ord(paragraph[local_cursor]) > 0xFFFF else 1


def _line_for_cursor(layout: QTextLayout, cursor: int) -> QTextLine | None:
    """Return the wrapped line containing one UTF-16 cursor boundary."""
    if layout.lineCount() == 0:
        return None
    for index in range(layout.lineCount()):
        line = layout.lineAt(index)
        if line.textStart() <= cursor <= line.textStart() + line.textLength():
            return line
    return layout.lineAt(layout.lineCount() - 1)


def _append_glyph_outlines(
    layout: QTextLayout,
    outline: QPainterPath,
    x_offset: float,
    y_offset: float,
    *,
    start: int = 0,
    length: int = -1,
) -> None:
    """Convert shaped glyph runs into one local-space outline path."""
    for glyph_run in layout.glyphRuns(start, length):
        raw_font = glyph_run.rawFont()
        for glyph_index, position in zip(
            glyph_run.glyphIndexes(),
            glyph_run.positions(),
            strict=True,
        ):
            glyph = raw_font.pathForGlyph(glyph_index)
            outline.addPath(
                QTransform.fromTranslate(
                    x_offset + position.x(),
                    y_offset + position.y(),
                ).map(glyph)
            )


def _paragraph_style_runs(
    content: VectorTextContent,
    paragraph_start: int,
    paragraph_length: int,
) -> tuple[tuple[int, int, VectorTextStyle], ...]:
    """Return contiguous effective character styles for one paragraph."""
    if paragraph_length <= 0:
        return ()
    styles = [content.style] * paragraph_length
    paragraph_end = paragraph_start + paragraph_length
    for span in content.spans:
        start = max(paragraph_start, span.start)
        end = min(paragraph_end, span.start + span.length)
        if start < end:
            styles[start - paragraph_start : end - paragraph_start] = [span.style] * (
                end - start
            )
    runs: list[tuple[int, int, VectorTextStyle]] = []
    start = 0
    while start < paragraph_length:
        style = styles[start]
        end = start + 1
        while end < paragraph_length and styles[end] == style:
            end += 1
        runs.append((start, end - start, style))
        start = end
    return tuple(runs)


def _paragraph_formats(
    content: VectorTextContent,
    paragraph_start: int,
    paragraph_length: int,
) -> list[QTextLayout.FormatRange]:
    """Project Python-codepoint style spans into one Qt UTF-16 paragraph."""
    paragraph_end = paragraph_start + paragraph_length
    formats: list[QTextLayout.FormatRange] = []
    for span in content.spans:
        start = max(paragraph_start, span.start)
        end = min(paragraph_end, span.start + span.length)
        if start >= end:
            continue
        local_start = start - paragraph_start
        local_end = end - paragraph_start
        paragraph = content.text[paragraph_start:paragraph_end]
        value = QTextLayout.FormatRange()
        value.start = _utf16_length(paragraph[:local_start])
        value.length = _utf16_length(paragraph[local_start:local_end])
        value.format = _character_format(span.style)
        formats.append(value)
    return formats


def _text_option(style: VectorParagraphStyle) -> QTextOption:
    """Translate semantic paragraph policy into detached Qt options."""
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    option.setAlignment(
        {
            VectorTextAlignment.LEFT: Qt.AlignmentFlag.AlignLeft,
            VectorTextAlignment.CENTER: Qt.AlignmentFlag.AlignHCenter,
            VectorTextAlignment.RIGHT: Qt.AlignmentFlag.AlignRight,
            VectorTextAlignment.JUSTIFY: Qt.AlignmentFlag.AlignJustify,
        }[style.alignment]
    )
    if style.direction is VectorTextDirection.LEFT_TO_RIGHT:
        option.setTextDirection(Qt.LayoutDirection.LeftToRight)
    elif style.direction is VectorTextDirection.RIGHT_TO_LEFT:
        option.setTextDirection(Qt.LayoutDirection.RightToLeft)
    return option


def _character_format(style: VectorTextStyle) -> QTextCharFormat:
    """Translate one semantic character style into Qt shaping values."""
    value = QTextCharFormat()
    value.setFont(_font(style))
    value.setForeground(style.color)
    return value


def _font(style: VectorTextStyle) -> QFont:
    """Build one requested font without mutating semantic style state."""
    font = QFont()
    font.setFamilies(list(style.families))
    font.setPixelSize(max(1, round(style.font_size)))
    font.setWeight(QFont.Weight(style.weight))
    font.setItalic(style.italic)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, style.letter_spacing)
    return font


def _font_resolutions(
    content: VectorTextContent,
) -> tuple[TextFontResolution, ...]:
    """Return stable diagnostics for every distinct requested character style."""
    styles = (content.style, *(span.style for span in content.spans))
    resolutions: list[TextFontResolution] = []
    seen: set[tuple[object, ...]] = set()
    for style in styles:
        key = _style_key(style)
        if key in seen:
            continue
        seen.add(key)
        requested_font = _font(style)
        info = QFontInfo(requested_font)
        resolutions.append(
            TextFontResolution(
                style.families,
                info.family() or requested_font.family(),
                info.exactMatch(),
            )
        )
    return tuple(resolutions)


def _layout_key(content: VectorTextContent, bounds: QRectF) -> Hashable:
    """Return a hashable semantic identity without retaining mutable Qt values."""
    return (
        content.text,
        _style_key(content.style),
        tuple(
            (span.start, span.length, _style_key(span.style)) for span in content.spans
        ),
        content.paragraph.alignment.value,
        content.paragraph.direction.value,
        content.paragraph.line_height,
        bounds.x(),
        bounds.y(),
        bounds.width(),
        bounds.height(),
    )


def _style_key(style: VectorTextStyle) -> tuple[object, ...]:
    """Return one immutable font-and-color cache key."""
    return (
        style.families,
        style.font_size,
        style.weight,
        style.italic,
        style.letter_spacing,
        style.color.rgba(),
    )


def _utf16_length(value: str) -> int:
    """Return Qt's UTF-16 code-unit length for a Python Unicode slice."""
    return len(value.encode("utf-16-le")) // 2
