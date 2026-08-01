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
"""Present authoritative mask history replay in one mounted canvas view."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from PySide6.QtCore import QRect

from .coverage_history import MaskCoverageCommand
from .mask import MaskAssetStore
from .mask_undo import MaskHistoryChange, MaskImageCommand
from .render_cache import MaskRenderCache
from .surface_history import MaskSurfaceCommand


class MaskHistoryPresenter:
    """Apply one document history change to one view's derived presentation."""

    def __init__(
        self,
        *,
        assets: MaskAssetStore,
        renders: MaskRenderCache,
        mask_changed: Callable[[uuid.UUID | None, QRect], None],
        undo_changed: Callable[[uuid.UUID], None],
        structure_changed: Callable[[], None],
    ) -> None:
        """Bind view-local derived state and presentation notifications."""
        self._assets = assets
        self._renders = renders
        self._mask_changed = mask_changed
        self._undo_changed = undo_changed
        self._structure_changed = structure_changed

    def present(self, change: MaskHistoryChange) -> bool:
        """Present ``change`` once and return whether it changed source geometry."""
        mask_id = change.mask_id
        layer = self._assets.get_layer(mask_id)
        structure_changed = _changes_structure(change)
        applied_delta = bool(
            layer is not None
            and change.has_snippets
            and self._renders.apply_history_delta(layer, change)
        )
        if structure_changed:
            if layer is not None:
                self._renders.invalidate_layer(layer)
            self._structure_changed()
        elif applied_delta:
            dirty_rect = QRect(change.snippets[0].rect)
            for snippet in change.snippets[1:]:
                dirty_rect = dirty_rect.united(snippet.rect)
            self._mask_changed(mask_id, dirty_rect)
        else:
            if layer is not None:
                self._renders.invalidate_layer(layer)
            self._mask_changed(mask_id, QRect())
        self._undo_changed(mask_id)
        return structure_changed


def _changes_structure(change: MaskHistoryChange) -> bool:
    """Return whether history replay changes the resource's storage bounds."""
    command = change.command
    if isinstance(command, MaskSurfaceCommand):
        return command.before.bounds != command.after.bounds
    if isinstance(command, MaskImageCommand):
        return command.before.size() != command.after.size()
    return isinstance(command, MaskCoverageCommand)
