#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Bounded persistent geometry trees for exact vector-mask unions."""

from __future__ import annotations

import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtGui import QPainterPath

from .geometry import object_path
from .model import VectorDocument, VectorObject
from .text_layout import SemanticTextLayoutCache


@dataclass(frozen=True, slots=True)
class _MaskPathTree:
    """Retain reusable union levels for one vector-mask object set."""

    objects: tuple[VectorObject, ...]
    levels: tuple[tuple[QPainterPath, ...], ...]
    resolved_path: QPainterPath
    last_changed: frozenset[int]
    stable_path: QPainterPath | None
    retained_bytes: int

    @property
    def path(self) -> QPainterPath:
        """Return the root union or an empty path."""
        return QPainterPath(self.resolved_path)


class VectorMaskPathCache:
    """Reuse unchanged union branches across immutable document revisions."""

    def __init__(
        self,
        budget_bytes: int = 8 * 1024 * 1024,
        *,
        text_layouts: SemanticTextLayoutCache | None = None,
    ) -> None:
        """Initialize an empty least-recently-used geometry cache."""
        self._budget_bytes = max(0, int(budget_bytes))
        self._usage_bytes = 0
        self._entries: OrderedDict[
            tuple[uuid.UUID, frozenset[uuid.UUID] | None],
            _MaskPathTree,
        ] = OrderedDict()
        self._usage_changed: Callable[[int], None] | None = None
        self._text_layouts = text_layouts

    @property
    def usage_bytes(self) -> int:
        """Return estimated retained path storage."""
        return self._usage_bytes

    @property
    def entry_count(self) -> int:
        """Return the number of retained mask projections."""
        return len(self._entries)

    def set_usage_changed(self, callback: Callable[[int], None] | None) -> None:
        """Install shared-cache usage publication."""
        self._usage_changed = callback

    def set_budget(self, budget_bytes: int) -> None:
        """Apply a strict cache budget and trim immediately."""
        self._budget_bytes = max(0, int(budget_bytes))
        self.trim_to(self._budget_bytes)

    def trim_to(self, target_bytes: int) -> None:
        """Evict oldest geometry trees until usage meets ``target_bytes``."""
        target = max(0, int(target_bytes))
        while self._entries and self._usage_bytes > target:
            _key, entry = self._entries.popitem(last=False)
            self._usage_bytes -= entry.retained_bytes
        self._report()

    def path(
        self,
        document: VectorDocument,
        object_ids: frozenset[uuid.UUID] | None,
    ) -> QPainterPath:
        """Return the exact union while rebuilding only changed tree branches."""
        key = (document.vector_id, object_ids)
        previous = self._entries.pop(key, None)
        if previous is not None:
            self._usage_bytes -= previous.retained_bytes
        objects = tuple(
            item
            for item in document.objects
            if object_ids is None or item.object_id in object_ids
        )
        entry = _update_tree(previous, objects, self._text_layouts)
        if entry.retained_bytes <= self._budget_bytes:
            self._entries[key] = entry
            self._usage_bytes += entry.retained_bytes
            self.trim_to(self._budget_bytes)
        else:
            self._report()
        return entry.path

    def _report(self) -> None:
        """Publish exact retained usage after mutations."""
        if self._usage_changed is not None:
            self._usage_changed(self._usage_bytes)


def _update_tree(
    previous: _MaskPathTree | None,
    objects: tuple[VectorObject, ...],
    text_layouts: SemanticTextLayoutCache | None,
) -> _MaskPathTree:
    """Reuse one compatible union tree and replace affected ancestors only."""
    compatible = bool(
        previous is not None
        and tuple(item.object_id for item in previous.objects)
        == tuple(item.object_id for item in objects)
    )
    if not objects:
        return _MaskPathTree((), (), QPainterPath(), frozenset(), None, 128)
    if not compatible or previous is None:
        levels = _build_levels(
            tuple(object_path(item, text_layouts) for item in objects)
        )
        return _tree(objects, levels, levels[-1][0])

    changed = {
        index for index, item in enumerate(objects) if item != previous.objects[index]
    }
    if not changed:
        return previous
    leaves = list(previous.levels[0])
    for index in changed:
        leaves[index] = object_path(objects[index], text_layouts)
    changed_indices = frozenset(changed)
    if changed_indices == previous.last_changed:
        stable_path = (
            previous.stable_path
            if previous.stable_path is not None
            else _stable_union(
                previous.levels,
                changed_indices,
                len(objects),
            )
        )
        changed_path = _build_levels(tuple(leaves[index] for index in changed))[-1][0]
        resolved_path = stable_path.united(changed_path)
        levels = (tuple(leaves), *previous.levels[1:])
        return _tree(
            objects,
            levels,
            resolved_path,
            last_changed=changed_indices,
            stable_path=stable_path,
        )
    if previous.stable_path is not None:
        rebuilt_levels = _build_levels(tuple(leaves))
        return _tree(
            objects,
            rebuilt_levels,
            rebuilt_levels[-1][0],
            last_changed=changed_indices,
        )
    levels: list[tuple[QPainterPath, ...]] = [tuple(leaves)]
    affected = changed
    for level_index in range(1, len(previous.levels)):
        prior_level = levels[level_index - 1]
        current_level = list(previous.levels[level_index])
        affected = {index // 2 for index in affected}
        for index in affected:
            left = prior_level[index * 2]
            right_index = index * 2 + 1
            current_level[index] = (
                left
                if right_index >= len(prior_level)
                else left.united(prior_level[right_index])
            )
        levels.append(tuple(current_level))
    frozen_levels = tuple(levels)
    return _tree(
        objects,
        frozen_levels,
        frozen_levels[-1][0],
        last_changed=changed_indices,
    )


def _build_levels(
    leaves: tuple[QPainterPath, ...],
) -> tuple[tuple[QPainterPath, ...], ...]:
    """Build a balanced union tree to avoid quadratic accumulation."""
    levels = [leaves]
    while len(levels[-1]) > 1:
        previous = levels[-1]
        levels.append(
            tuple(
                (
                    previous[index]
                    if index + 1 == len(previous)
                    else previous[index].united(previous[index + 1])
                )
                for index in range(0, len(previous), 2)
            )
        )
    return tuple(levels)


def _tree(
    objects: tuple[VectorObject, ...],
    levels: tuple[tuple[QPainterPath, ...], ...],
    resolved_path: QPainterPath,
    *,
    last_changed: frozenset[int] = frozenset(),
    stable_path: QPainterPath | None = None,
) -> _MaskPathTree:
    """Create one entry with a conservative geometry-retention estimate."""
    element_count = sum(path.elementCount() for level in levels for path in level)
    element_count += resolved_path.elementCount()
    if stable_path is not None:
        element_count += stable_path.elementCount()
    return _MaskPathTree(
        objects,
        levels,
        resolved_path,
        last_changed,
        stable_path,
        max(128, element_count * 32),
    )


def _stable_union(
    levels: tuple[tuple[QPainterPath, ...], ...],
    excluded: frozenset[int],
    leaf_count: int,
) -> QPainterPath:
    """Union maximal unchanged branches around repeatedly edited leaves."""
    branches: list[QPainterPath] = []

    def collect(level: int, index: int) -> None:
        """Collect the largest cached node that excludes every hot leaf."""
        start = index * (1 << level)
        end = min(leaf_count, start + (1 << level))
        if not any(start <= leaf < end for leaf in excluded):
            branches.append(levels[level][index])
            return
        if level == 0:
            return
        child_level = level - 1
        left_index = index * 2
        collect(child_level, left_index)
        right_index = left_index + 1
        if right_index < len(levels[child_level]):
            collect(child_level, right_index)

    collect(len(levels) - 1, 0)
    if not branches:
        return QPainterPath()
    return _build_levels(tuple(branches))[-1][0]
