#    QPane + CuteCanvas - High-performance PySide6 rendering and editing
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
"""Validate API-reference completeness and meaningful tutorial coverage."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from re import Pattern

from .model import ProductContract

_REFERENCE_HEADING = re.compile(
    r"\b(?:API Reference|Full API|Field Reference|Fields)\b",
    re.IGNORECASE,
)
_BARE_SYMBOL = re.compile(
    r"^\s*(?:[-*+]\s*)?(?:`)?[A-Z][A-Za-z0-9_]*"
    r"(?:\.[A-Za-z0-9_]+)?(?:`)?\s*(?:[:\-–—]?\s*)?$"
)
_CODE_SPAN = re.compile(r"`[^`]*`")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_'-]*")


@dataclass(frozen=True, slots=True)
class MarkdownBlock:
    """Represent one coarse Markdown block and its tutorial context."""

    kind: str
    text: str
    path: Path
    line: int
    rejected_section: bool = False
    rejected_list_run: bool = False


def build_symbol_pattern(symbols: Iterable[str]) -> Pattern[str]:
    """Return an exact pattern for top-level symbols and qualified members."""
    roots = {symbol.split(".", 1)[0] for symbol in symbols}
    if not roots:
        return re.compile(r"(?!x)x")
    joined = "|".join(
        sorted((re.escape(root) for root in roots), key=len, reverse=True)
    )
    return re.compile(rf"\b(?:{joined})(?:\.[A-Za-z_][A-Za-z0-9_]*)?\b")


def validate_documentation(
    product: ProductContract,
    expected_symbols: set[str],
) -> list[str]:
    """Return reference, guide-quality, completeness, and ghost errors."""
    expected = {
        symbol
        for symbol in expected_symbols
        if not symbol.split(".")[-1].startswith("_") and symbol != "__version__"
    }
    pattern = build_symbol_pattern(expected)
    reference_mentions, reference_errors = collect_api_reference_symbols(
        product.api_reference,
        pattern,
    )
    _guide_mentions, guide_errors = collect_valid_guide_symbols(product.guides, pattern)
    all_guide_mentions = collect_symbols(product.guides, pattern)
    strict_member_roots = {
        symbol.split(".", 1)[0] for symbol in expected if "." in symbol
    }
    reference = _contract_symbols(reference_mentions, expected)
    reference_ghosts = _ghost_symbols(
        reference_mentions,
        expected,
        strict_member_roots,
    )
    guide_ghosts = _ghost_symbols(
        all_guide_mentions,
        expected,
        strict_member_roots,
    )
    errors = [
        f"{product.package}: {error}" for error in (*reference_errors, *guide_errors)
    ]
    errors.extend(
        f"{product.package}: [API Reference] Missing: {symbol}"
        for symbol in sorted(expected - reference)
    )
    errors.extend(
        f"{product.package}: [API Reference] Ghost: {symbol}"
        for symbol in sorted(reference_ghosts)
    )
    errors.extend(
        f"{product.package}: [Guides] Ghost: {symbol}"
        for symbol in sorted(guide_ghosts)
    )
    return errors


def _contract_symbols(mentions: set[str], expected: set[str]) -> set[str]:
    """Map qualified mentions of re-exported types to their top-level contract."""
    symbols = set(mentions)
    symbols.update(
        root for mention in mentions if (root := mention.split(".", 1)[0]) in expected
    )
    return symbols


def _ghost_symbols(
    mentions: set[str],
    expected: set[str],
    strict_member_roots: set[str],
) -> set[str]:
    """Allow members of typed re-exports while rejecting unknown facade members."""
    ghosts: set[str] = set()
    for mention in mentions:
        root = mention.split(".", 1)[0]
        if mention in expected:
            continue
        if "." in mention and root in expected and root not in strict_member_roots:
            continue
        ghosts.add(mention)
    return ghosts


def collect_valid_guide_symbols(
    paths: Iterable[Path],
    symbol_pattern: Pattern[str],
) -> tuple[set[str], list[str]]:
    """Return symbols taught with explanatory prose and guide-quality errors."""
    symbols: set[str] = set()
    errors: list[str] = []
    for path in paths:
        if not path.exists():
            errors.append(f"[Guides] Missing document: {path}")
            continue
        blocks = parse_markdown_blocks(path)
        for block in blocks:
            if block.kind == "heading" and block.rejected_section:
                errors.append(
                    f"[Guides] Reference-style heading in {path.name}:{block.line}: "
                    f"{block.text}"
                )
            if block.kind == "list" and block.rejected_list_run:
                errors.append(
                    f"[Guides] Symbol dump in {path.name}:{block.line}; "
                    "rewrite as workflow prose"
                )
        for index, block in enumerate(blocks):
            block_symbols = set(symbol_pattern.findall(block.text))
            if not block_symbols:
                continue
            if block_has_explanatory_prose(block, symbol_pattern):
                symbols.update(block_symbols)
                continue
            if block.kind == "code" and not block.rejected_section:
                nearby = (
                    blocks[max(0, index - 2) : index]
                    + blocks[index + 1 : min(len(blocks), index + 3)]
                )
                for symbol in block_symbols:
                    if any(
                        symbol in candidate.text
                        and block_has_explanatory_prose(candidate, symbol_pattern)
                        for candidate in nearby
                    ):
                        symbols.add(symbol)
                continue
            if block.kind in {"paragraph", "list"} and (
                block.rejected_section
                or block.rejected_list_run
                or _BARE_SYMBOL.match(block.text)
                or block_is_bare_symbol_mention(block, symbol_pattern)
            ):
                errors.append(
                    f"[Guides] Bare symbol mention in {path.name}:{block.line}: "
                    + ", ".join(sorted(block_symbols))
                )
    return symbols, errors


def collect_api_reference_symbols(
    path: Path,
    symbol_pattern: Pattern[str],
) -> tuple[set[str], list[str]]:
    """Return reference symbols that have a same-block explanation."""
    if not path.exists():
        return set(), [f"[API Reference] Missing document: {path}"]
    symbols: set[str] = set()
    errors: list[str] = []
    for block in parse_markdown_blocks(path):
        block_symbols = set(symbol_pattern.findall(block.text))
        if not block_symbols or "](" in block.text:
            continue
        if block.kind == "heading":
            symbols.update(block_symbols)
        elif block.kind in {"paragraph", "list"}:
            if explanatory_word_count(block.text, symbol_pattern) >= 2:
                symbols.update(block_symbols)
            else:
                errors.append(
                    f"[API Reference] Missing short explainer in "
                    f"{path.name}:{block.line}: " + ", ".join(sorted(block_symbols))
                )
    return symbols, errors


def collect_symbols(paths: Iterable[Path], pattern: Pattern[str]) -> set[str]:
    """Return every contract-shaped symbol mentioned by the documents."""
    symbols: set[str] = set()
    for path in paths:
        if path.exists():
            symbols.update(pattern.findall(path.read_text(encoding="utf-8")))
    return symbols


def parse_markdown_blocks(path: Path) -> list[MarkdownBlock]:
    """Parse Markdown into blocks used for documentation quality decisions."""
    if not path.exists():
        return []
    blocks: list[MarkdownBlock] = []
    heading_rejections: list[tuple[int, bool]] = []
    paragraph: list[str] = []
    paragraph_line = 0
    code: list[str] = []
    code_line = 0
    in_code = False

    def rejected_section() -> bool:
        return any(rejected for _level, rejected in heading_rejections)

    def flush(kind: str, parts: list[str], line: int) -> None:
        text = " ".join(part.strip() for part in parts).strip()
        if text:
            blocks.append(MarkdownBlock(kind, text, path, line, rejected_section()))
        parts.clear()

    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_code:
                flush("code", code, code_line)
            else:
                flush("paragraph", paragraph, paragraph_line)
                code_line = line_number
            in_code = not in_code
            continue
        if in_code:
            code.append(line)
            continue
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            flush("paragraph", paragraph, paragraph_line)
            level = len(heading.group(1))
            title = heading.group(2).strip()
            while heading_rejections and heading_rejections[-1][0] >= level:
                heading_rejections.pop()
            heading_rejections.append((level, bool(_REFERENCE_HEADING.search(title))))
            blocks.append(
                MarkdownBlock(
                    "heading",
                    title,
                    path,
                    line_number,
                    rejected_section(),
                )
            )
            continue
        if not stripped:
            flush("paragraph", paragraph, paragraph_line)
            paragraph_line = 0
            continue
        list_item = re.match(r"^\s*(?:[-*+]|\d+[.)])\s+(.+)$", line)
        if list_item:
            flush("paragraph", paragraph, paragraph_line)
            blocks.append(
                MarkdownBlock(
                    "list",
                    list_item.group(1).strip(),
                    path,
                    line_number,
                    rejected_section(),
                )
            )
            continue
        if not paragraph:
            paragraph_line = line_number
        paragraph.append(line)
    flush(
        "code" if in_code else "paragraph",
        code if in_code else paragraph,
        code_line if in_code else paragraph_line,
    )
    return _mark_symbol_dumps(blocks)


def _mark_symbol_dumps(blocks: list[MarkdownBlock]) -> list[MarkdownBlock]:
    """Mark long consecutive bare-symbol lists as invalid tutorial coverage."""
    result = list(blocks)
    run: list[int] = []

    def finish_run() -> None:
        if len(run) > 12:
            for index in run:
                result[index] = replace(result[index], rejected_list_run=True)
        run.clear()

    for index, block in enumerate(result):
        if block.kind == "list" and _BARE_SYMBOL.match(block.text):
            run.append(index)
        else:
            finish_run()
    finish_run()
    return result


def explanatory_word_count(text: str, pattern: Pattern[str]) -> int:
    """Return a conservative count of explanatory non-symbol words."""
    cleaned = pattern.sub(" ", _CODE_SPAN.sub(" ", text))
    ignored = {"http", "https", "md", "py", "true", "false", "none"}
    return sum(1 for token in _WORD.findall(cleaned) if token.lower() not in ignored)


def block_is_bare_symbol_mention(
    block: MarkdownBlock,
    pattern: Pattern[str],
) -> bool:
    """Return whether a block contains symbols without enough explanation."""
    symbols = pattern.findall(block.text)
    return bool(symbols) and explanatory_word_count(block.text, pattern) < len(symbols)


def block_has_explanatory_prose(
    block: MarkdownBlock,
    pattern: Pattern[str],
    *,
    minimum_words: int = 8,
) -> bool:
    """Return whether a narrative block meaningfully explains its symbols."""
    return (
        not block.rejected_section
        and not block.rejected_list_run
        and block.kind in {"paragraph", "list"}
        and not _BARE_SYMBOL.match(block.text)
        and not block_is_bare_symbol_mention(block, pattern)
        and explanatory_word_count(block.text, pattern) >= minimum_words
    )
