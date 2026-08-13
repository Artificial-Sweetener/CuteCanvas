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
"""Clone Stamp source identity and stroke alignment over rendered scene pixels."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor

from qpane.sdk.rendering import (
    LayerLocalPoint,
    PanelPoint,
    SceneCoordinateSystem,
    ScenePoint,
)
from qpane.sdk.scene import LayerDescriptor, LayerTransform, SceneDescriptor

from .clone_model import (
    CloneStampAlignment,
    CloneStampMapping,
    CloneStampSampleMode,
    CloneStampState,
    CloneStampTransform,
)
from .clone_source import CloneStampSourceResolver
from .model import BrushPreset, BrushStrokeSegment
from .sample_mapping import AffineSampleMapping
from .target_contracts import PaintTargetContext


@runtime_checkable
class CloneStampTarget(Protocol):
    """Apply Clone Stamp mappings to one editable target domain."""

    def supports_clone(self, target: PaintTargetContext) -> bool:
        """Return whether ``target`` accepts cloned color pixels."""
        ...

    def begin_clone(self, target: PaintTargetContext) -> bool:
        """Begin one atomic clone transaction."""
        ...

    def apply_clone(
        self,
        target: PaintTargetContext,
        segment: BrushStrokeSegment,
        preset: BrushPreset,
        mapping: CloneStampMapping,
    ) -> bool:
        """Apply one semantic segment from its immutable source mapping."""
        ...

    def commit_clone(self, target: PaintTargetContext) -> bool:
        """Commit one complete clone stroke."""
        ...

    def cancel_clone(self, target: PaintTargetContext) -> bool:
        """Restore the target state preceding the active clone stroke."""
        ...


class CloneStampOperation:
    """Own an independent rendered source anchor and clone-stroke alignment."""

    def __init__(
        self,
        *,
        target: CloneStampTarget,
        current_scene: Callable[[], SceneDescriptor | None],
        selected_layer: Callable[[], LayerDescriptor | None],
        coordinates: SceneCoordinateSystem,
        changed: Callable[[CloneStampState], None] | None = None,
    ) -> None:
        """Bind scene, selection, target pixels, and coordinate authorities."""
        self._target = target
        self._current_scene = current_scene
        self._selected_layer = selected_layer
        self._coordinates = coordinates
        self._source_resolver = CloneStampSourceResolver(
            selected_layer=selected_layer,
            coordinates=coordinates,
        )
        self._changed = changed
        self._state = CloneStampState()
        self._stroke_mapping: CloneStampMapping | None = None
        self._stroke_configuration_changed = False
        self._aligned_sample_mapping: AffineSampleMapping | None = None
        self._effective_source: ScenePoint | None = None
        self._pre_stroke_source: ScenePoint | None = None

    @property
    def state(self) -> CloneStampState:
        """Return the immutable current Clone Stamp state."""
        return self._state

    @property
    def stroke_active(self) -> bool:
        """Return whether one source mapping is frozen for an active stroke."""
        return self._stroke_mapping is not None

    def sample_linear_transform(self) -> LayerTransform:
        """Return the active or configured destination-to-source linear map."""
        mapping = self._stroke_mapping
        return (
            self._state.transform._inverse_content_transform()
            if mapping is None
            else mapping.sample_mapping.destination_to_source
        )

    def destination_layer(self) -> LayerDescriptor | None:
        """Return the selected destination layer used for footprint projection."""
        return self._selected_layer()

    def set_alignment(self, alignment: CloneStampAlignment) -> bool:
        """Set whether the canvas-space source offset persists between strokes."""
        normalized = CloneStampAlignment(alignment)
        if normalized is self._state.alignment:
            return False
        self._state = CloneStampState(
            alignment=normalized,
            sample_mode=self._state.sample_mode,
            transform=self._state.transform,
            source=self._state.source,
        )
        self._configuration_changed()
        self._publish()
        return True

    def set_sample_mode(self, mode: CloneStampSampleMode) -> bool:
        """Choose the rendered layer range sampled by subsequent strokes."""
        normalized = CloneStampSampleMode(mode)
        if normalized is self._state.sample_mode:
            return False
        source = self._source_resolver.for_mode(
            self._state.source,
            self._current_scene(),
            normalized,
        )
        self._state = CloneStampState(
            alignment=self._state.alignment,
            sample_mode=normalized,
            transform=self._state.transform,
            source=source,
        )
        self._configuration_changed()
        self._publish()
        return True

    def set_transform(self, transform: CloneStampTransform) -> bool:
        """Set the visible transform applied to subsequent cloned content."""
        if not isinstance(transform, CloneStampTransform):
            raise TypeError("transform must be CloneStampTransform")
        if transform == self._state.transform:
            return False
        self._state = CloneStampState(
            alignment=self._state.alignment,
            sample_mode=self._state.sample_mode,
            transform=transform,
            source=self._state.source,
        )
        self._configuration_changed()
        self._publish()
        return True

    def set_source_from_panel(self, panel_point: QPointF) -> bool:
        """Set an independent source anchor from one panel-space position."""
        scene = self._current_scene()
        if scene is None:
            return False
        point = self._coordinates.panel_to_scene(PanelPoint.from_qt(panel_point))
        if point is None or point.scene_id != scene.scene_id:
            return False
        return self._set_source(scene, point)

    def set_source(self, scene_point: QPointF) -> bool:
        """Set a source anchor in the active composition's scene coordinates."""
        scene = self._current_scene()
        if scene is None:
            return False
        return self._set_source(
            scene,
            ScenePoint.from_qt(scene.scene_id, scene_point),
        )

    def clear_source(self) -> bool:
        """Clear the source anchor and every retained aligned offset."""
        if self._state.source is None:
            return False
        self._state = CloneStampState(
            alignment=self._state.alignment,
            sample_mode=self._state.sample_mode,
            transform=self._state.transform,
            source=None,
        )
        self._configuration_changed()
        self._publish()
        return True

    def source_is_available(self) -> bool:
        """Return whether the configured source exists in the active scene."""
        scene = self._current_scene()
        return scene is not None and self._source_resolver.is_valid(
            self._state.source,
            scene,
            self._state.sample_mode,
        )

    def source_scene_point(self) -> QPointF | None:
        """Return the effective source point in active-scene coordinates."""
        scene = self._current_scene()
        if scene is None or not self._source_resolver.is_valid(
            self._state.source,
            scene,
            self._state.sample_mode,
        ):
            return None
        effective = self._effective_source
        return (
            self._state.source.scene_point()
            if effective is None and self._state.source is not None
            else effective.to_qt() if effective is not None else None
        )

    def source_panel_point(self) -> QPointF | None:
        """Project the effective source marker through QPane's current view."""
        scene = self._current_scene()
        point = self.source_scene_point()
        if scene is None or point is None:
            return None
        panel = self._coordinates.scene_to_panel(
            ScenePoint.from_qt(scene.scene_id, point)
        )
        return None if panel is None else panel.to_qt()

    def supports(self, target: PaintTargetContext) -> bool:
        """Return whether Clone Stamp can write to this destination."""
        return self._target.supports_clone(target)

    def begin(self, target: PaintTargetContext) -> bool:
        """Freeze source identity before opening one destination transaction."""
        if not self._source_resolver.is_valid(
            self._state.source,
            target.scene,
            self._state.sample_mode,
        ):
            return False
        self._stroke_mapping = None
        self._stroke_configuration_changed = False
        self._pre_stroke_source = self._effective_source
        return self._target.begin_clone(target)

    def apply(
        self,
        target: PaintTargetContext,
        segment: BrushStrokeSegment,
        preset: BrushPreset,
        color: QColor,
    ) -> bool:
        """Resolve one canvas-space source offset and apply the segment."""
        del color
        mapping = self._stroke_mapping
        if mapping is None:
            mapping = self._mapping_for(target, segment)
            if mapping is None:
                return False
            self._stroke_mapping = mapping
        applied = self._target.apply_clone(target, segment, preset, mapping)
        if applied:
            self._effective_source = self._effective_source_point(
                target,
                mapping,
                QPointF(*segment.end),
            )
        return applied

    def commit(self, target: PaintTargetContext) -> bool:
        """Commit pixels, retain alignment, and restore anchor feedback."""
        committed = self._target.commit_clone(target)
        if (
            committed
            and self._state.alignment is CloneStampAlignment.ALIGNED
            and self._stroke_mapping is not None
            and not self._stroke_configuration_changed
        ):
            self._aligned_sample_mapping = self._stroke_mapping.sample_mapping
        if committed:
            self._effective_source = None
        else:
            self._effective_source = self._pre_stroke_source
        self._stroke_mapping = None
        self._stroke_configuration_changed = False
        self._pre_stroke_source = None
        return committed

    def cancel(self, target: PaintTargetContext) -> bool:
        """Cancel target pixels without changing the retained aligned offset."""
        self._stroke_mapping = None
        self._effective_source = (
            None if self._stroke_configuration_changed else self._pre_stroke_source
        )
        self._stroke_configuration_changed = False
        self._pre_stroke_source = None
        return self._target.cancel_clone(target)

    def preview_color(self, target: PaintTargetContext, fallback: QColor) -> QColor:
        """Return a neutral high-visibility clone feedback color."""
        del target, fallback
        return QColor(255, 255, 255)

    def _set_source(
        self,
        scene: SceneDescriptor,
        scene_point: ScenePoint,
    ) -> bool:
        """Install one source anchored to the current mode's scene authority."""
        source = self._source_resolver.create(
            scene,
            scene_point,
            self._state.sample_mode,
        )
        if source is None:
            return False
        self._state = CloneStampState(
            alignment=self._state.alignment,
            sample_mode=self._state.sample_mode,
            transform=self._state.transform,
            source=source,
        )
        self._configuration_changed()
        self._publish()
        return True

    def _configuration_changed(self) -> None:
        """Apply new configuration after any already-frozen stroke mapping."""
        self._aligned_sample_mapping = None
        if self._stroke_mapping is None:
            self._effective_source = None
            self._pre_stroke_source = None
            return
        self._stroke_configuration_changed = True

    def _mapping_for(
        self,
        target: PaintTargetContext,
        segment: BrushStrokeSegment,
    ) -> CloneStampMapping | None:
        """Freeze source offset and rendered layer scope for one stroke."""
        source = self._state.source
        layer = target.layer
        if source is None or layer is None:
            return None
        destination_scene = self._coordinates.layer_local_to_scene(
            LayerLocalPoint.from_qt(
                target.scene.scene_id,
                layer.layer_id,
                QPointF(*segment.start),
            )
        )
        if destination_scene is None:
            return None
        sample_mapping = self._aligned_sample_mapping
        if (
            self._state.alignment is CloneStampAlignment.UNALIGNED
            or sample_mapping is None
        ):
            sample_mapping = AffineSampleMapping.anchored(
                destination_anchor=destination_scene.to_qt(),
                source_anchor=source.scene_point(),
                inverse_content_transform=(
                    self._state.transform._inverse_content_transform()
                ),
            )
        return CloneStampMapping(
            source,
            sample_mapping,
            self._source_resolver.layer_scope(
                target.scene,
                source,
                self._state.sample_mode,
            ),
        )

    def _effective_source_point(
        self,
        target: PaintTargetContext,
        mapping: CloneStampMapping,
        destination: QPointF,
    ) -> ScenePoint | None:
        """Resolve the exact canvas-space source sampled at one destination."""
        layer = target.layer
        if layer is None:
            return None
        destination_scene = self._coordinates.layer_local_to_scene(
            LayerLocalPoint.from_qt(
                target.scene.scene_id,
                layer.layer_id,
                destination,
            )
        )
        if destination_scene is None:
            return None
        sampled = mapping.sample_mapping.map_point(destination_scene.to_qt())
        return ScenePoint(
            target.scene.scene_id,
            sampled.x(),
            sampled.y(),
        )

    def _publish(self) -> None:
        """Publish one complete immutable state observation."""
        if self._changed is not None:
            self._changed(self._state)
