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
"""User-facing mask layer lifecycle workflows."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QImage

from .file_io import MaskImageLoader
from .layer_coordination import MaskLayerCoordinator
from .mask import MaskAssetStore, MaskLayer
from .mask_controller import MaskController
from .render_coordination import MaskRenderWorkCoordinator

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from ..canvas import CuteCanvas


class MaskLayerWorkflow:
    """Coordinate mask import, creation, removal, and stack commands."""

    def __init__(
        self,
        *,
        qpane: CuteCanvas,
        assets: MaskAssetStore,
        controller: MaskController,
        layers: MaskLayerCoordinator,
        render_work: MaskRenderWorkCoordinator,
        activate_mask: Callable[[uuid.UUID | None], bool],
        reset_strokes: Callable[..., None],
        invalidate_jobs: Callable[..., None],
        commit_image: Callable[..., bool],
        publish_status: Callable[..., None],
    ) -> None:
        """Bind owners required to coordinate complete mask layer commands."""
        self._qpane = qpane
        self._assets = assets
        self._controller = controller
        self._layers = layers
        self._render_work = render_work
        self._activate_mask = activate_mask
        self._reset_strokes = reset_strokes
        self._invalidate_jobs = invalidate_jobs
        self._commit_image = commit_image
        self._publish_status = publish_status

    def load_from_path(
        self,
        path: str,
        *,
        undoable: bool = True,
    ) -> uuid.UUID | None:
        """Import a mask and optionally record its admission in history."""
        scene = self._qpane.currentScene()
        composition_id = self._qpane.currentCompositionID()
        if composition_id is None or scene is None:
            self._publish_status(
                "Cannot load a mask without an active composition.",
                label="Mask Error",
            )
            return None
        target_size = QSize(
            max(1, round(scene.bounds.width())),
            max(1, round(scene.bounds.height())),
        )
        prepared = self._prepare_from_path(
            path,
            target_size=target_size,
            failure_message=f"Failed to load or prepare mask from {path}",
        )
        if prepared is None:
            return None
        if undoable:
            seed = QImage(target_size, QImage.Format_Grayscale8)
            seed.fill(0)
            mask_id = self._assets.create_mask(seed)
            if not self._commit_image(mask_id, prepared):
                return None
        else:
            mask_id = self._assets.create_mask_from_image(prepared)
        layer = self._assets.get_layer(mask_id)
        layer_index = len(self._layers.mask_ids_for_composition(composition_id))
        if layer is None or not self._layers.attach_to_composition(
            mask_id,
            composition_id,
            color=random_mask_color(layer_index),
            undoable=undoable,
        ):
            self._assets.delete_mask(mask_id)
            return None
        self._activate_mask(mask_id)
        self._qpane.markDirty()
        self._qpane.update()
        self._publish_status(
            f"Successfully loaded mask data from {path} as new layer ({mask_id}).",
            label="Mask",
        )
        return mask_id

    def update_from_path(self, mask_id: uuid.UUID, path: str) -> bool:
        """Replace mask pixels for mask_id with data from path."""
        layer = self._assets.get_layer(mask_id)
        if layer is None:
            self._publish_status(
                f"Update failed: no mask layer found for {mask_id}",
                label="Mask Error",
            )
            return False
        prepared = self._prepare_from_path(
            path,
            target_size=layer.mask_image.size(),
            failure_message=f"Update failed: could not prepare mask from {path}",
        )
        if prepared is None or not self._commit_image(mask_id, prepared):
            return False
        self._notify_replaced(mask_id, f"Mask {mask_id} updated from {path}")
        return True

    def update_from_image(self, mask_id: uuid.UUID, image: QImage) -> bool:
        """Replace mask pixels for mask_id with detached host image data."""
        layer = self._assets.get_layer(mask_id)
        if layer is None:
            self._publish_status(
                f"Update failed: no mask layer found for {mask_id}",
                label="Mask Error",
            )
            return False
        prepared = MaskImageLoader.normalize(image, layer.mask_image.size())
        if prepared is None or not self._commit_image(mask_id, prepared):
            self._publish_status(
                f"Update failed: could not prepare mask image for {mask_id}",
                label="Mask Error",
            )
            return False
        self._notify_replaced(mask_id, f"Mask {mask_id} updated from image")
        return True

    def _notify_replaced(self, mask_id: uuid.UUID, message: str) -> None:
        """Publish redraw and status after one committed mask replacement."""
        self._qpane.markDirty()
        self._qpane.repaint()
        self._publish_status(message, label="Mask")

    def create_blank(
        self,
        size: QSize,
        *,
        undoable: bool = True,
    ) -> uuid.UUID | None:
        """Create a blank mask and optionally record its admission in history."""
        if size.isNull() or not size.isValid():
            self._publish_status(
                "Cannot create blank mask with invalid size.", label="Mask Error"
            )
            return None
        composition_id = self._qpane.currentCompositionID()
        if composition_id is None:
            self._publish_status(
                "Cannot create blank mask without an active composition.",
                label="Mask Error",
            )
            return None
        template = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
        template.fill(Qt.transparent)
        layer_index = len(self._layers.mask_ids_for_composition(composition_id))
        mask_id = self._assets.create_mask(template)
        color = random_mask_color(layer_index)
        if not self._layers.attach_to_composition(
            mask_id,
            composition_id,
            color=color,
            undoable=undoable,
        ):
            self._assets.delete_mask(mask_id)
            return None
        self._layers.update_presentation(mask_id, color=color)
        self._qpane.markDirty()
        self._qpane.update()
        self._publish_status(f"Created blank mask layer ({mask_id}).", label="Mask")
        return mask_id

    def remove_from_composition(
        self,
        composition_id: uuid.UUID,
        mask_id: uuid.UUID,
    ) -> bool:
        """Remove a mask instance and refresh edit/render lifecycle state."""
        if composition_id is None:
            self._publish_status(
                "Cannot remove mask because the document identifier is missing.",
                label="Mask Error",
            )
            return False
        was_active = self._controller.get_active_mask_id() == mask_id
        layer = self._assets.get_layer(mask_id)
        if not self._layers.remove(composition_id, mask_id):
            self._publish_status(
                f"Mask {mask_id} is not associated with document {composition_id}.",
                label="Mask Error",
            )
            return False
        self._render_work.prioritize_interaction(mask_id)
        self._controller.renders.invalidate_layer(layer)
        self._controller.edits.advance_epoch(mask_id, reason="mask_removed")
        self._reset_strokes(mask_id, request_redraw=False)
        self._controller.edits.discard_source(mask_id)
        remaining_ids = self._layers.mask_ids_for_composition(composition_id)
        next_active = remaining_ids[-1] if remaining_ids else None
        if was_active:
            self._controller.setActiveMaskID(next_active)
        else:
            self._controller.active_mask_properties_changed.emit()
            self._controller.mask_updated.emit(None, QRect())
        self._qpane.markDirty()
        self._qpane.update()
        self._publish_status(
            f"Removed mask {mask_id} from document {composition_id}.",
            label="Mask",
        )
        return True

    def set_properties(
        self,
        mask_id: uuid.UUID,
        *,
        color: QColor | None = None,
        opacity: float | None = None,
    ) -> bool:
        """Update composition-owned presentation for a mask layer."""
        return self._layers.update_presentation(
            mask_id,
            color=color,
            opacity=opacity,
        )

    def cycle(self, composition_id: uuid.UUID | None, *, forward: bool) -> None:
        """Cycle masks in one document or the active composition."""
        previous_active = self._controller.get_active_mask_id()
        composition_id = composition_id or self._qpane.currentCompositionID()
        mask_ids = (
            []
            if composition_id is None
            else self._layers.mask_ids_for_composition(composition_id)
        )
        moved = False
        if len(mask_ids) >= 2:
            assert composition_id is not None
            moving_mask = mask_ids[0] if forward else mask_ids[-1]
            target_index = self._layers.mask_stack_end_index(forward=forward)
            routed = (
                self._layers.route_reorder(moving_mask, target_index)
                if target_index is not None
                else None
            )
            moved = (
                self._layers.reorder_mask_slot_in_composition(
                    composition_id,
                    moving_mask,
                    len(mask_ids) - 1 if forward else 0,
                )
                if routed is None
                else routed
            )
        new_order = (
            []
            if composition_id is None
            else self._layers.mask_ids_for_composition(composition_id)
        )
        new_top = new_order[-1] if moved and new_order else None
        direction = "forward" if forward else "backward"
        if new_top:
            if previous_active is not None and previous_active != new_top:
                self._invalidate_jobs(previous_active, reason="mask_reordered")
            self._reset_strokes(new_top, request_redraw=False)
            self._controller.setActiveMaskID(new_top)
            self._publish_status(
                f"Cycled {direction} mask order; {new_top} is now active.",
                label="Mask",
            )
        else:
            self._publish_status(
                f"Cycling {direction} mask order for {composition_id} had no effect.",
                label="Mask",
            )

    def promote_to_top(self, mask_id: uuid.UUID) -> bool:
        """Bring mask_id to the top of the active composition's mask stack."""
        composition_id = self._qpane.currentCompositionID()
        if composition_id is None:
            self._publish_status(
                "Cannot promote a mask without an active composition.",
                label="Mask Error",
            )
            return False
        mask_ids = self._layers.mask_ids_for_composition(composition_id)
        if mask_id not in mask_ids:
            was_moved = False
        else:
            top_scene_index = self._layers.mask_stack_end_index(forward=True)
            routed = (
                self._layers.route_reorder(mask_id, top_scene_index)
                if top_scene_index is not None
                else None
            )
            was_moved = (
                self._layers.reorder_mask_slot_in_composition(
                    composition_id,
                    mask_id,
                    len(mask_ids) - 1,
                )
                if routed is None
                else routed
            )
        if was_moved:
            self._publish_status(
                f"Promoted mask {mask_id} to the top of the stack.", label="Mask"
            )
        else:
            self._publish_status(
                f"Mask {mask_id} is already at the top or not associated with the current image.",
                label="Mask Error",
            )
        return was_moved

    def handle_region_update(
        self, dirty_image_rect: QRect, mask_layer_supplier: Callable[[], object]
    ) -> None:
        """Render externally edited mask pixels supplied on demand."""
        layer = mask_layer_supplier()
        if layer is None:
            return
        self._render_work.update_region(dirty_image_rect, cast(MaskLayer, layer))

    def _prepare_from_path(
        self,
        path: str,
        *,
        target_size: QSize,
        failure_message: str,
        failure_label: str = "Mask Error",
    ) -> QImage | None:
        """Load and normalize mask image data from path."""
        prepared = MaskImageLoader.load(path, target_size)
        if prepared is None:
            self._publish_status(failure_message, label=failure_label)
        return prepared


def random_mask_color(layer_index: int = 0) -> QColor:
    """Generate a deterministic color for a new mask layer."""
    golden_ratio = 0.6180339887498949
    hue_fraction = (layer_index * golden_ratio) % 1.0
    hue = int(hue_fraction * 359)
    return QColor.fromHsv(hue, 200, 255)
