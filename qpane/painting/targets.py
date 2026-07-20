#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Typed paint-target registration and active-target interaction routing."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from PySide6.QtCore import QPoint, QPointF
from PySide6.QtGui import QColor

from ..composition.resource_lifetime import (
    CompositionResourceLifetime,
    ResourceLeaseKind,
)
from ..scene.model import LayerDescriptor, SceneDescriptor
from ..scene.mutations import SceneMutationCoordinator
from ..scene.source_references import LayerSourceReference
from ..types import PaintTargetKind
from .compositor import BrushCompositor
from .configuration import BrushStrokeCompiler
from .model import BrushPreset, BrushStrokeSegment


@dataclass(frozen=True, slots=True)
class PaintTargetIdentity:
    """Identify one composition-local destination selected for painting."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID | None
    kind: PaintTargetKind = PaintTargetKind.LAYER

    def __post_init__(self) -> None:
        """Reject contradictory target identities."""
        kind = PaintTargetKind(self.kind)
        if kind is PaintTargetKind.LAYER and self.layer_id is None:
            raise ValueError("layer paint targets require a layer_id")
        if kind is not PaintTargetKind.LAYER and self.layer_id is not None:
            raise ValueError("scene paint targets must not include a layer_id")
        object.__setattr__(self, "kind", kind)


@dataclass(frozen=True, slots=True)
class PaintTargetContext:
    """Resolve one paint identity to its scene and optional layer snapshot."""

    identity: PaintTargetIdentity
    scene: SceneDescriptor
    layer: LayerDescriptor | None


@runtime_checkable
class PaintTargetOwner(Protocol):
    """Implement paint transactions for one typed layer source domain."""

    def supports(self, target: PaintTargetContext) -> bool:
        """Return whether this owner exclusively handles ``target``."""
        ...

    def begin(self, target: PaintTargetContext) -> bool:
        """Begin one atomic paint history transaction."""
        ...

    def apply(
        self,
        target: PaintTargetContext,
        segment: BrushStrokeSegment,
        preset: BrushPreset,
        color: QColor,
    ) -> bool:
        """Apply one deterministic segment to the active transaction."""
        ...

    def commit(self, target: PaintTargetContext) -> bool:
        """Commit the active transaction as one history command."""
        ...

    def cancel(self, target: PaintTargetContext) -> bool:
        """Restore pixels captured before the active transaction."""
        ...

    def preview_color(self, target: PaintTargetContext, fallback: QColor) -> QColor:
        """Return the target-appropriate brush feedback color."""
        ...


class PaintTargetRegistry:
    """Route paint operations to one authoritative owner per source type."""

    def __init__(self) -> None:
        """Initialize an empty ordered owner collection."""
        self._owners: list[PaintTargetOwner] = []
        self._idle_feedback: dict[object, Callable[[QColor], QColor | None]] = {}

    def register(self, owner: PaintTargetOwner) -> PaintTargetOwner:
        """Register one owner exactly once."""
        if owner not in self._owners:
            self._owners.append(owner)
        return owner

    def unregister(self, owner: PaintTargetOwner) -> None:
        """Remove one owner without disturbing other domains."""
        self._owners = [
            candidate for candidate in self._owners if candidate is not owner
        ]
        self._idle_feedback.pop(owner, None)

    def register_idle_feedback(
        self,
        owner: object,
        provider: Callable[[QColor], QColor | None],
    ) -> None:
        """Register optional brush feedback shown before a target exists."""
        self._idle_feedback[owner] = provider

    def idle_preview_color(self, fallback: QColor) -> QColor | None:
        """Return the first available passive brush-feedback color."""
        for provider in self._idle_feedback.values():
            color = provider(QColor(fallback))
            if isinstance(color, QColor) and color.isValid():
                return QColor(color)
        return None

    def owner_for(self, target: PaintTargetContext) -> PaintTargetOwner | None:
        """Return the sole owner that advertises ``target`` support."""
        matches = [owner for owner in self._owners if owner.supports(target)]
        if len(matches) > 1:
            raise RuntimeError("multiple paint target owners support one layer")
        return None if not matches else matches[0]


class PaintingCoordinator:
    """Own active paint-target selection and source-neutral stroke lifecycle."""

    def __init__(
        self,
        *,
        scenes: SceneMutationCoordinator,
        panel_to_source: Callable[
            [uuid.UUID, uuid.UUID, QPoint | QPointF], QPointF | None
        ],
        source_to_panel: Callable[
            [uuid.UUID, uuid.UUID, QPoint | QPointF], QPointF | None
        ],
        panel_to_scene: Callable[[QPoint | QPointF], QPointF | None],
        scene_to_panel: Callable[[QPoint | QPointF], QPointF | None],
        preset: BrushPreset | None = None,
        changed: Callable[[PaintTargetIdentity | None], None] | None = None,
        compositor: BrushCompositor | None = None,
        resource_lifetime: CompositionResourceLifetime | None = None,
    ) -> None:
        """Bind scene resolution and coordinate adapters."""
        self.registry = PaintTargetRegistry()
        self._scenes = scenes
        self._panel_to_source = panel_to_source
        self._source_to_panel = source_to_panel
        self._panel_to_scene = panel_to_scene
        self._scene_to_panel = scene_to_panel
        self._changed = changed
        self._identity: PaintTargetIdentity | None = None
        self._active_owner: PaintTargetOwner | None = None
        self._stroke_context: PaintTargetContext | None = None
        self._stroke_source: LayerSourceReference | None = None
        self._requires_policy = True
        self._stroke_open = False
        self._preset = BrushPreset() if preset is None else preset
        self._color = QColor(0, 0, 0, 255)
        self._compiler = BrushStrokeCompiler()
        self._compositor = BrushCompositor() if compositor is None else compositor
        self._resource_lifetime = resource_lifetime

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

    def select_layer(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        *,
        require_policy: bool = True,
    ) -> bool:
        """Select one policy-enabled paint-capable active layer."""
        identity = PaintTargetIdentity(scene_id, layer_id)
        resolved = self._resolve(identity)
        if resolved is None:
            return False
        target, owner = resolved
        layer = target.layer
        if layer is None or require_policy and not layer.interaction.pixel_editable:
            return False
        if identity == self._identity:
            return True
        self.cancel()
        self._identity = identity
        self._active_owner = owner
        self._requires_policy = bool(require_policy)
        self._publish()
        return True

    def select_pixel_selection(self, scene_id: uuid.UUID) -> bool:
        """Select composition pixel-selection coverage as the paint target."""
        identity = PaintTargetIdentity(
            scene_id,
            None,
            PaintTargetKind.PIXEL_SELECTION,
        )
        resolved = self._resolve(identity)
        if resolved is None:
            return False
        if identity == self._identity:
            return True
        self.cancel()
        self._identity = identity
        self._active_owner = resolved[1]
        self._requires_policy = False
        self._publish()
        return True

    def clear(self) -> bool:
        """Cancel active work and clear selected paint-target identity."""
        if self._identity is None:
            return False
        self.cancel()
        self._identity = None
        self._active_owner = None
        self._requires_policy = True
        self._publish()
        return True

    def begin(self) -> bool:
        """Begin one target-owned atomic stroke transaction."""
        if self._stroke_open:
            return True
        resolved = self._current()
        if resolved is None:
            return False
        target, owner = resolved
        self._stroke_open = owner.begin(target)
        self._stroke_context = target if self._stroke_open else None
        self._active_owner = owner if self._stroke_open else self._active_owner
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
        resolved = self._current()
        if resolved is None:
            self._cancel_open_transaction()
            return False
        target, owner = resolved
        return owner.apply(target, segment, self._preset, self._color)

    def commit(self) -> bool:
        """Commit active target work exactly once."""
        if not self._stroke_open:
            return False
        resolved = self._current()
        if resolved is None:
            self._cancel_open_transaction()
            return False
        target, owner = resolved
        try:
            return owner.commit(target)
        finally:
            self._stroke_open = False
            self._stroke_context = None
            self._release_stroke_resource()

    def cancel(self) -> bool:
        """Cancel active target work without changing target selection."""
        if not self._stroke_open:
            return False
        return self._cancel_open_transaction()

    def panel_to_target(self, point: QPoint | QPointF) -> QPointF | None:
        """Map panel geometry into the selected target's source coordinates."""
        identity = self._resolved_identity()
        if identity is None:
            return None
        if identity.kind is PaintTargetKind.PIXEL_SELECTION:
            return self._panel_to_scene(point)
        if identity.layer_id is None:
            return None
        return self._panel_to_source(identity.scene_id, identity.layer_id, point)

    def target_to_panel(self, point: QPoint | QPointF) -> QPointF | None:
        """Map selected target source geometry into panel coordinates."""
        identity = self._resolved_identity()
        if identity is None:
            return None
        if identity.kind is PaintTargetKind.PIXEL_SELECTION:
            return self._scene_to_panel(point)
        if identity.layer_id is None:
            return None
        return self._source_to_panel(identity.scene_id, identity.layer_id, point)

    def preview_color(self) -> QColor | None:
        """Return target-appropriate feedback color when a target is current."""
        resolved = self._current()
        if resolved is None:
            return self.registry.idle_preview_color(self._color)
        target, owner = resolved
        return QColor(owner.preview_color(target, self._color))

    def diameter_for_pressure(self, pressure: float) -> float:
        """Resolve target-neutral pressure preview geometry from the active preset."""
        return self._compiler.diameter_for_pressure(pressure, self._preset)

    def _resolved_identity(self) -> PaintTargetIdentity | None:
        """Clear stale identity when its scene, layer, policy, or owner disappears."""
        identity = self._identity
        if identity is None:
            return None
        resolved = self._resolve(identity)
        layer = None if resolved is None else resolved[0].layer
        if resolved is not None and (
            not self._requires_policy
            or layer is not None
            and layer.interaction.pixel_editable
        ):
            return identity
        self._cancel_open_transaction()
        self._identity = None
        self._active_owner = None
        self._requires_policy = True
        self._publish()
        return None

    def _cancel_open_transaction(self) -> bool:
        """Cancel through the captured transaction even after scene invalidation."""
        if not self._stroke_open:
            return False
        owner = self._active_owner
        target = self._stroke_context
        self._stroke_open = False
        self._stroke_context = None
        try:
            return False if owner is None or target is None else owner.cancel(target)
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
        identity = self._resolved_identity()
        if identity is None:
            return None
        return self._resolve(identity)

    def _resolve(
        self,
        identity: PaintTargetIdentity,
    ) -> tuple[PaintTargetContext, PaintTargetOwner] | None:
        """Resolve one exact active-scene destination and its sole owner."""
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
        target = PaintTargetContext(identity, scene, layer)
        owner = self.registry.owner_for(target)
        return None if owner is None else (target, owner)

    def _publish(self) -> None:
        """Notify presentation after active target identity changes."""
        if self._changed is not None:
            self._changed(self._identity)
