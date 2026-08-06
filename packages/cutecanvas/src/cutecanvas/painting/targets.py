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
"""Typed paint-target registration and active-target interaction routing."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, QPointF
from PySide6.QtGui import QColor
from qpane.sdk.rendering import (
    LayerLocalPoint,
    PanelPoint,
    SceneCoordinateSystem,
    ScenePoint,
)
from qpane.sdk.scene import LayerSourceReference

from ..composition.resource_lifetime import (
    CompositionResourceLifetime,
    ResourceLeaseKind,
)
from ..scene.mutations import SceneMutationCoordinator
from ..types import PaintTargetKind
from .compositor import BrushCompositor
from .configuration import BrushStrokeCompiler
from .model import BrushPreset, BrushStrokeSegment
from .operations import BrushStrokeOperation, DirectBrushStrokeOperation
from .target_contracts import (
    CoverageFillTargetOwner,
    FloodFillSource,
    FloodFillTargetOwner,
    PaintTargetContext,
    PaintTargetIdentity,
    PaintTargetOwner,
    PaintTargetRegistry,
    RetainedCoverageTargetOwner,
)

if TYPE_CHECKING:
    from cutecanvas.coverage import CoverageItem, CoverageSnapshot
    from cutecanvas.coverage.operations import CoverageCombineMode


class PaintingCoordinator:
    """Own active paint-target selection and source-neutral stroke lifecycle."""

    def __init__(
        self,
        *,
        scenes: SceneMutationCoordinator,
        coordinates: SceneCoordinateSystem,
        preset: BrushPreset | None = None,
        changed: Callable[[PaintTargetIdentity | None], None] | None = None,
        compositor: BrushCompositor | None = None,
        resource_lifetime: CompositionResourceLifetime | None = None,
    ) -> None:
        """Bind scene resolution and coordinate adapters."""
        self.registry = PaintTargetRegistry()
        self._scenes = scenes
        self._coordinates = coordinates
        self._changed = changed
        self._identity: PaintTargetIdentity | None = None
        self._stroke_context: PaintTargetContext | None = None
        self._stroke_source: LayerSourceReference | None = None
        self._requires_policy = True
        self._stroke_open = False
        self._preset = BrushPreset() if preset is None else preset
        self._color = QColor(0, 0, 0, 255)
        self._compiler = BrushStrokeCompiler()
        self._compositor = BrushCompositor() if compositor is None else compositor
        self._resource_lifetime = resource_lifetime
        self._direct_operation = DirectBrushStrokeOperation(self.registry)
        self._stroke_operation: BrushStrokeOperation = self._direct_operation
        self._transaction_operation: BrushStrokeOperation | None = None

    @property
    def identity(self) -> PaintTargetIdentity | None:
        """Return the selected paint target after pruning stale state."""
        return self._resolved_identity()

    @property
    def preset(self) -> BrushPreset:
        """Return the immutable active brush preset."""
        return self._preset

    @property
    def color(self) -> QColor:
        """Return a detached active paint color."""
        return QColor(self._color)

    @property
    def compositor(self) -> BrushCompositor:
        """Return the shared compositor and its coordinated tip cache."""
        return self._compositor

    def set_preset(self, preset: BrushPreset) -> bool:
        """Replace the brush configuration used by subsequent segments."""
        if not isinstance(preset, BrushPreset):
            raise TypeError("preset must be BrushPreset")
        if preset == self._preset:
            return False
        self._preset = preset
        return True

    def set_color(self, color: QColor) -> bool:
        """Replace the detached color used by color-capable targets."""
        if not isinstance(color, QColor) or not color.isValid():
            raise TypeError("color must be a valid QColor")
        if color == self._color:
            return False
        self._color = QColor(color)
        return True

    def set_stroke_operation(self, operation: BrushStrokeOperation) -> bool:
        """Replace the injected brush behavior used by subsequent strokes."""
        if not isinstance(operation, BrushStrokeOperation):
            raise TypeError("operation must implement BrushStrokeOperation")
        if operation is self._stroke_operation:
            return False
        self.cancel()
        self._stroke_operation = operation
        self._resolved_identity()
        self._publish()
        return True

    def use_direct_stroke_operation(self) -> bool:
        """Restore ordinary paint/erase behavior for the shared brush tool."""
        return self.set_stroke_operation(self._direct_operation)

    def select_layer(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        *,
        require_policy: bool = True,
    ) -> bool:
        """Select one policy-enabled paint-capable active layer."""
        identity = PaintTargetIdentity(scene_id, layer_id)
        target = self._resolve_context(identity)
        if target is None:
            return False
        layer = target.layer
        if (
            layer is None
            or require_policy
            and not layer.interaction.pixel_editable
            or not self._stroke_operation.supports(target)
        ):
            return False
        if identity == self._identity:
            return True
        self.cancel()
        self._identity = identity
        self._requires_policy = bool(require_policy)
        self._publish()
        return True

    def supports_context(
        self,
        target: PaintTargetContext,
        *,
        require_policy: bool = True,
    ) -> bool:
        """Return whether the current operation accepts one layer context."""
        layer = target.layer
        return bool(
            layer is not None
            and (not require_policy or layer.interaction.pixel_editable)
            and self._stroke_operation.supports(target)
        )

    def select_pixel_selection(self, scene_id: uuid.UUID) -> bool:
        """Select composition pixel-selection coverage as the paint target."""
        identity = PaintTargetIdentity(
            scene_id,
            None,
            PaintTargetKind.PIXEL_SELECTION,
        )
        target = self._resolve_context(identity)
        if target is None or not self._stroke_operation.supports(target):
            return False
        if identity == self._identity:
            return True
        self.cancel()
        self._identity = identity
        self._requires_policy = False
        self._publish()
        return True

    def clear(self) -> bool:
        """Cancel active work and clear selected paint-target identity."""
        if self._identity is None:
            return False
        self.cancel()
        self._identity = None
        self._requires_policy = True
        self._publish()
        return True

    def begin(self) -> bool:
        """Begin one target-owned atomic stroke transaction."""
        if self._stroke_open:
            return True
        target = self.current_context()
        if target is None:
            return False
        operation = self._stroke_operation
        self._stroke_open = operation.begin(target)
        self._stroke_context = target if self._stroke_open else None
        self._transaction_operation = operation if self._stroke_open else None
        source = None if target.layer is None else target.layer.source
        if (
            self._stroke_open
            and source is not None
            and self._resource_lifetime is not None
        ):
            self._resource_lifetime.acquire(source, ResourceLeaseKind.SESSION)
            self._stroke_source = source
        return self._stroke_open

    def apply(self, segment: BrushStrokeSegment) -> bool:
        """Route one deterministic segment to the current target owner."""
        if not isinstance(segment, BrushStrokeSegment):
            return False
        if not self._stroke_open and not self.begin():
            return False
        target = self.current_context()
        if target is None:
            self._cancel_open_transaction()
            return False
        operation = self._transaction_operation
        return bool(
            operation is not None
            and operation.apply(
                target,
                segment,
                self._preset,
                self._color,
            )
        )

    def commit(self) -> bool:
        """Commit active target work exactly once."""
        if not self._stroke_open:
            return False
        target = self.current_context()
        if target is None:
            self._cancel_open_transaction()
            return False
        operation = self._transaction_operation
        try:
            return bool(operation is not None and operation.commit(target))
        finally:
            self._stroke_open = False
            self._stroke_context = None
            self._transaction_operation = None
            self._release_stroke_resource()

    def cancel(self) -> bool:
        """Cancel active target work without changing target selection."""
        if not self._stroke_open:
            return False
        return self._cancel_open_transaction()

    def panel_to_target(self, point: QPoint | QPointF) -> QPointF | None:
        """Map panel geometry into stable target-local coordinates."""
        identity = self._resolved_identity()
        if identity is None:
            return None
        panel_point = PanelPoint.from_qt(point)
        if identity.kind is PaintTargetKind.PIXEL_SELECTION:
            scene_point = self._coordinates.panel_to_scene(panel_point)
            return None if scene_point is None else scene_point.to_qt()
        if identity.layer_id is None:
            return None
        local_point = self._coordinates.panel_to_layer_local(
            identity.scene_id,
            identity.layer_id,
            panel_point,
        )
        return None if local_point is None else local_point.to_qt()

    def target_to_panel(self, point: QPoint | QPointF) -> QPointF | None:
        """Map selected target source geometry into panel coordinates."""
        identity = self._resolved_identity()
        if identity is None:
            return None
        if identity.kind is PaintTargetKind.PIXEL_SELECTION:
            panel_point = self._coordinates.scene_to_panel(
                ScenePoint.from_qt(identity.scene_id, point)
            )
            return None if panel_point is None else panel_point.to_qt()
        if identity.layer_id is None:
            return None
        panel_point = self._coordinates.layer_local_to_panel(
            LayerLocalPoint.from_qt(
                identity.scene_id,
                identity.layer_id,
                point,
            )
        )
        return None if panel_point is None else panel_point.to_qt()

    def preview_color(self) -> QColor | None:
        """Return target-appropriate feedback color when a target is current."""
        resolved = self._current()
        if resolved is None:
            return self.registry.idle_preview_color(self._color)
        target, _owner = resolved
        if not self._stroke_operation.supports(target):
            return None
        return QColor(self._stroke_operation.preview_color(target, self._color))

    def can_commit_coverage_item(self) -> bool:
        """Return whether the selected destination accepts retained coverage."""
        resolved = self._current()
        return bool(
            resolved is not None
            and isinstance(resolved[1], RetainedCoverageTargetOwner)
        )

    def commit_coverage_item(self, item: CoverageItem) -> bool:
        """Route one semantic coverage item through the selected destination."""
        resolved = self._current()
        if resolved is None or not isinstance(resolved[1], RetainedCoverageTargetOwner):
            return False
        return resolved[1].commit_coverage_item(resolved[0], item)

    def flood_fill_source(
        self,
    ) -> tuple[PaintTargetContext, FloodFillSource] | None:
        """Return one current target sample when paint-bucket editing is supported."""
        resolved = self._current()
        if resolved is None or not isinstance(resolved[1], FloodFillTargetOwner):
            return None
        sample = resolved[1].flood_fill_source(resolved[0])
        return None if sample is None else (resolved[0], sample)

    def can_flood_fill(self) -> bool:
        """Return whether the selected destination supports Paint Bucket."""
        resolved = self._current()
        return bool(
            resolved is not None and isinstance(resolved[1], FloodFillTargetOwner)
        )

    def current_context(self) -> PaintTargetContext | None:
        """Return the current resolved target context for editor coordinators."""
        return self._validated_context()

    def can_fill_coverage(self) -> bool:
        """Return whether the selected destination accepts bounded coverage fills."""
        resolved = self._current()
        return bool(
            resolved is not None and isinstance(resolved[1], CoverageFillTargetOwner)
        )

    def commit_fill_coverage(
        self,
        context: PaintTargetContext,
        coverage: CoverageSnapshot,
        mode: CoverageCombineMode,
    ) -> bool:
        """Commit target-local coverage while its destination remains active."""
        resolved = self._current()
        if (
            resolved is None
            or resolved[0].identity != context.identity
            or not isinstance(resolved[1], CoverageFillTargetOwner)
        ):
            return False
        return resolved[1].commit_fill_coverage(
            resolved[0],
            coverage,
            mode,
            self._color,
        )

    def commit_flood_fill(
        self,
        context: PaintTargetContext,
        coverage: CoverageSnapshot,
        mode: CoverageCombineMode,
        expected_revision: object,
    ) -> bool:
        """Publish current, non-stale paint-bucket coverage atomically."""
        resolved = self._current()
        if (
            resolved is None
            or resolved[0].identity != context.identity
            or not isinstance(resolved[1], FloodFillTargetOwner)
        ):
            return False
        return resolved[1].commit_flood_fill(
            resolved[0],
            coverage,
            mode,
            expected_revision,
            self._color,
        )

    def diameter_for_pressure(self, pressure: float) -> float:
        """Resolve target-neutral pressure preview geometry from the active preset."""
        return self._compiler.diameter_for_pressure(pressure, self._preset)

    def _resolved_identity(self) -> PaintTargetIdentity | None:
        """Clear stale identity when its scene, layer, policy, or owner disappears."""
        context = self._validated_context()
        return None if context is None else context.identity

    def _validated_context(self) -> PaintTargetContext | None:
        """Resolve and validate the selected target once for one hot-path query."""
        identity = self._identity
        if identity is None:
            return None
        context = self._resolve_context(identity)
        layer = None if context is None else context.layer
        if (
            context is not None
            and self._stroke_operation.supports(context)
            and (
                not self._requires_policy
                or layer is not None
                and layer.interaction.pixel_editable
            )
        ):
            return context
        self._cancel_open_transaction()
        self._identity = None
        self._requires_policy = True
        self._publish()
        return None

    def _cancel_open_transaction(self) -> bool:
        """Cancel through the captured transaction even after scene invalidation."""
        if not self._stroke_open:
            return False
        operation = self._transaction_operation
        target = self._stroke_context
        self._stroke_open = False
        self._stroke_context = None
        self._transaction_operation = None
        try:
            return (
                False
                if operation is None or target is None
                else operation.cancel(target)
            )
        finally:
            self._release_stroke_resource()

    def _release_stroke_resource(self) -> None:
        """Release the generic session lease after target resolution finishes."""
        source = self._stroke_source
        self._stroke_source = None
        if source is not None and self._resource_lifetime is not None:
            self._resource_lifetime.release(source, ResourceLeaseKind.SESSION)

    def _current(
        self,
    ) -> tuple[PaintTargetContext, PaintTargetOwner] | None:
        """Resolve the selected identity and retain its current owner."""
        context = self._validated_context()
        if context is None:
            return None
        owner = self.registry.owner_for(context)
        return None if owner is None else (context, owner)

    def _resolve_context(
        self,
        identity: PaintTargetIdentity,
    ) -> PaintTargetContext | None:
        """Resolve one exact active-scene destination without choosing an operation."""
        scene = self._scenes.active_scene()
        if scene is None or scene.scene_id != identity.scene_id:
            return None
        layer = None
        if identity.layer_id is not None:
            layer = next(
                (
                    candidate
                    for candidate in scene.layers
                    if candidate.layer_id == identity.layer_id
                ),
                None,
            )
            if layer is None:
                return None
        return PaintTargetContext(identity, scene, layer)

    def _publish(self) -> None:
        """Notify presentation after active target identity changes."""
        if self._changed is not None:
            self._changed(self._identity)
