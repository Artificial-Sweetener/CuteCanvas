#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Panel interaction arbitration for selected-content and layer movement."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Literal

from PySide6.QtCore import QPointF

from ..scene.layer_selection import SceneLayerSelection
from ..scene.movement_interaction import SceneLayerMovementInteraction
from .pixel_movement import SelectedPixelMovementController


class EditorMovementInteraction:
    """Route one Move-tool sequence to the correct authoritative movement owner."""

    def __init__(
        self,
        *,
        pixels: SelectedPixelMovementController,
        layers: SceneLayerMovementInteraction,
        panel_to_scene: Callable[[QPointF], QPointF | None],
        refresh_preview: Callable[[], None],
    ) -> None:
        """Bind selected-pixel and layer-placement movement branches."""
        self._pixels = pixels
        self._layers = layers
        self._panel_to_scene = panel_to_scene
        self._refresh_preview = refresh_preview
        self._active: Literal["pixels", "layer"] | None = None
        self._selection_hover_valid = False

    @property
    def hovered(self) -> SceneLayerSelection | None:
        """Return layer hover only when whole-layer movement is eligible."""
        return None if self._pixels.has_selection() else self._layers.hovered

    @property
    def target_available(self) -> bool:
        """Return whether current hover identifies a valid movement target."""
        if self._pixels.has_selection():
            return self._selection_hover_valid
        return self._layers.hovered is not None

    def update_hover(self, panel_point: QPointF) -> bool:
        """Refresh target feedback without changing durable selection state."""
        if not self._pixels.has_selection():
            changed = self._selection_hover_valid
            self._selection_hover_valid = False
            return self._layers.update_hover(panel_point) or changed
        layer_changed = self._layers.clear_hover()
        scene_point = self._panel_to_scene(panel_point)
        valid = scene_point is not None and self._pixels.can_begin(scene_point)
        changed = valid != self._selection_hover_valid
        self._selection_hover_valid = valid
        if changed or layer_changed:
            self._refresh_preview()
        return changed or layer_changed

    def clear_hover(self) -> bool:
        """Clear selection and layer hover feedback."""
        selection_changed = self._selection_hover_valid
        self._selection_hover_valid = False
        layer_changed = self._layers.clear_hover()
        if selection_changed and not layer_changed:
            self._refresh_preview()
        return layer_changed or selection_changed

    def begin(self, panel_point: QPointF, copy: bool = False) -> bool:
        """Begin the selection-priority movement branch for one pointer sequence."""
        if self._active is not None:
            return False
        self.clear_hover()
        if self._pixels.has_selection():
            scene_point = self._panel_to_scene(panel_point)
            if scene_point is None or not self._pixels.begin(scene_point, copy):
                return False
            self._active = "pixels"
            return True
        if not self._layers.begin(panel_point):
            return False
        self._active = "layer"
        return True

    def update(self, panel_point: QPointF) -> bool:
        """Update the active movement branch."""
        if self._active == "layer":
            return self._layers.update(panel_point)
        if self._active != "pixels":
            return False
        scene_point = self._panel_to_scene(panel_point)
        return scene_point is not None and self._pixels.update(scene_point)

    def finish(self, panel_point: QPointF) -> bool:
        """Finish the active drag and clear sequence ownership."""
        active = self._active
        self._active = None
        if active == "layer":
            return self._layers.finish(panel_point)
        if active != "pixels":
            return False
        scene_point = self._panel_to_scene(panel_point)
        return scene_point is not None and self._pixels.finish(scene_point)

    def cancel(self) -> bool:
        """Cancel whichever movement branch owns the current sequence."""
        active = self._active
        self._active = None
        if active == "pixels":
            return self._pixels.cancel()
        if active == "layer":
            return self._layers.cancel()
        return self._pixels.cancel()

    def suspend(self) -> bool:
        """Release input ownership while preserving unresolved floating pixels."""
        active = self._active
        self._active = None
        if active == "pixels":
            return self._pixels.suspend_drag()
        if active == "layer":
            return self._layers.cancel()
        return False

    def nudge(self, delta_x: int, delta_y: int) -> bool:
        """Move selected pixels first, or the selected movable layer otherwise."""
        if self._pixels.has_selection():
            return self._pixels.nudge(delta_x, delta_y)
        return self._layers.nudge(delta_x, delta_y)

    def anchor_floating_pixels(self) -> bool:
        """Commit an unresolved floating edit to its source layer."""
        return self._pixels.anchor_to_source()

    def anchor_floating_pixels_to(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> bool:
        """Commit an unresolved floating edit to a compatible layer."""
        return self._pixels.anchor_to(scene_id, layer_id)

    def promote_floating_pixels(self, label: str | None = None) -> uuid.UUID | None:
        """Commit an unresolved floating edit as a new composition layer."""
        return self._pixels.promote_to_layer(label)

    @property
    def pixels(self) -> SelectedPixelMovementController:
        """Expose the selected-pixel owner to the facade adapter."""
        return self._pixels
