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

"""Mask feature state and signal coordination."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from PySide6.QtCore import QObject, QPoint, QPointF, QRect, Signal
from PySide6.QtGui import QColor, QImage

from ..core.config import Config
from ..core.config_features import MaskConfigSlice, require_mask_config
from .edit_service import MaskEditEpochs, MaskEditService
from .live_preview_store import MaskLivePreviewStore
from .mask import MaskAssetStore, MaskLayer
from .mask_diagnostics import MaskStrokeDiagnostics
from .render_cache import MaskRenderCache

DEFAULT_MASK_COLOR = QColor(255, 0, 0)


class MaskController(QObject):
    """Coordinate active selection, feature signals, edits, and derived renders."""

    mask_updated = Signal(object, QRect)
    render_dirty = Signal(object, QRect)
    active_mask_properties_changed = Signal()
    undo_stack_changed = Signal(object)

    def __init__(
        self,
        mask_manager: MaskAssetStore,
        source_to_panel_point: Callable[[QPoint], QPoint | QPointF | None],
        config: Config,
        mask_config: MaskConfigSlice | None = None,
        *,
        live_previews: MaskLivePreviewStore,
        stroke_diagnostics: MaskStrokeDiagnostics | None = None,
        color_for_mask: Callable[[uuid.UUID], QColor | None] | None = None,
        structure_changed: Callable[[], None] | None = None,
        render_scale: Callable[[], float] | None = None,
    ):
        """Initialize mask caches, coordinate transforms, and diagnostics hooks.

        Args:
            mask_manager: Manager providing mask data for each image.
            source_to_panel_point: Callable to convert mask-source coordinates for UI updates.
            config: Feature-aware configuration providing cache budgets.
            mask_config: Optional mask slice override when the caller already
                resolved the feature configuration.
            live_previews: Document-scoped provisional mask presentation owner.
            stroke_diagnostics: Optional diagnostics helper for stroke timing/counters.
            color_for_mask: Composition-owned mask appearance lookup.
            structure_changed: Callback for source-bounds geometry changes.
            render_scale: Current visible scale used for activation warming.
        """
        super().__init__()
        self._assets = mask_manager
        self._source_to_panel_point: Callable[[QPoint], QPoint | QPointF | None] = (
            source_to_panel_point
        )
        self._config_source = config
        self._mask_config = mask_config or require_mask_config(config)
        self._color_for_mask = color_for_mask or (lambda _mask_id: DEFAULT_MASK_COLOR)
        self._render_scale = render_scale or (lambda: 1.0)
        self._active_mask_id = None
        self._presentation_identity = object()
        self._epochs = MaskEditEpochs()
        self._renders = MaskRenderCache(
            mask_manager,
            source_to_panel_point,
            config,
            self._mask_config,
            live_previews=live_previews,
            active_mask_id=lambda: self._active_mask_id,
            async_epoch=self._epochs.current,
            color_for_mask=self.color_for_mask,
            render_changed=lambda mask_id, rect: self.render_dirty.emit(mask_id, rect),
            active_properties_changed=self.active_mask_properties_changed.emit,
        )
        self._edits = MaskEditService(
            mask_manager,
            self._renders,
            self._epochs,
            active_mask_id=lambda: self._active_mask_id,
            mask_changed=lambda mask_id, rect: self.mask_updated.emit(mask_id, rect),
            undo_changed=self.undo_stack_changed.emit,
            structure_changed=structure_changed,
            diagnostics=stroke_diagnostics,
            presentation_identity=self._presentation_identity,
        )

    @property
    def presentation_identity(self) -> object:
        """Return the opaque identity used to suppress self-originated replay."""
        return self._presentation_identity

    @property
    def renders(self) -> MaskRenderCache:
        """Return the owner of derived mask rasters and cache state."""
        return self._renders

    @property
    def edits(self) -> MaskEditService:
        """Return the owner of transactional mask edits and history."""
        return self._edits

    def _get_layer(self, mask_id) -> MaskLayer | None:
        """Return the mask layer for ``mask_id`` if it exists."""
        if mask_id is None:
            return None
        return self._assets.get_layer(mask_id)

    def _snapshot_layer_image(self, mask_layer: MaskLayer | None) -> QImage:
        """Return a detached grayscale snapshot for `mask_layer`."""
        if mask_layer is None:
            return QImage()
        return mask_layer.coverage.snapshot_qimage()

    def set_color_resolver(
        self, color_for_mask: Callable[[uuid.UUID], QColor | None]
    ) -> None:
        """Use composition-owned presentation values for mask rendering."""
        self._color_for_mask = color_for_mask
        self._renders.clear()

    def color_for_mask(self, mask_id: uuid.UUID | None) -> QColor:
        """Return the composition tint for ``mask_id`` or the factory default."""
        if mask_id is None:
            return QColor(DEFAULT_MASK_COLOR)
        color = self._color_for_mask(mask_id)
        return QColor(DEFAULT_MASK_COLOR if color is None else color)

    def setActiveMaskID(
        self, mask_id, *, warm_cache: bool = True, emit_signals: bool = True
    ) -> bool:
        """Set the currently editable mask, emitting only when it changes."""
        if mask_id == self._active_mask_id:
            return False
        self._active_mask_id = mask_id
        if warm_cache:
            self.warm_mask(mask_id)
        if emit_signals:
            self.emit_activation_signals(mask_id)
        return True

    def warm_mask(self, mask_id: uuid.UUID | None) -> None:
        """Warm one mask at the active view's current display density."""
        scale = max(1e-6, float(self._render_scale()))
        self._renders.warm(
            mask_id,
            scale=None if abs(scale - 1.0) < 1e-3 else scale,
        )

    def emit_activation_signals(self, mask_id: uuid.UUID | None) -> None:
        """Emit activation-related signals for one editable mask."""
        self.active_mask_properties_changed.emit()
        self.mask_updated.emit(mask_id, QRect())

    def getActiveMaskImage(self) -> QImage | None:
        """Return a detached snapshot of the active mask pixels."""
        layer = self._get_layer(self._active_mask_id)
        if layer is None:
            return None
        snapshot = self._snapshot_layer_image(layer)
        return None if snapshot.isNull() else snapshot

    def get_active_mask_color(self) -> QColor | None:
        """Return the composition tint of the active mask."""
        if self._get_layer(self._active_mask_id) is None:
            return None
        return self.color_for_mask(self._active_mask_id)

    def get_active_mask_id(self) -> uuid.UUID | None:
        """Return the currently editable mask id."""
        return self._active_mask_id
