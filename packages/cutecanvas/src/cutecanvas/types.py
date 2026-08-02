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
"""Public editor and document value types."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF
from PySide6.QtGui import QColor, QImage, QTransform

if TYPE_CHECKING:
    from .placed.model import PlacedAssetMode, PlacedAssetStatus

__all__ = [
    "CompositionEntry",
    "CompositionLayerClip",
    "CompositionLayerEntry",
    "CompositionPolicy",
    "CompositionSnapshot",
    "ControlMode",
    "CoverageCoordinateSpace",
    "DiagnosticsDomain",
    "EditorCapability",
    "EditorIntent",
    "EditorOperationState",
    "EditorPolicy",
    "FloatingPixelMode",
    "FloatingPixelSnapshot",
    "LayerHit",
    "LayerPolicy",
    "LayerSelectionSnapshot",
    "LayerSnapshot",
    "MaskSavedPayload",
    "MoveToolOptions",
    "NonEditablePaintPolicy",
    "PaintTargetKind",
    "PaintTargetSnapshot",
    "PixelSelectionMode",
    "PixelSelectionSnapshot",
    "PlacedAssetSnapshot",
    "RasterExtentPolicy",
    "RasterSurfaceSnapshot",
    "SceneSnapshot",
]


MaskSavedPayload = tuple[str, str]


class DiagnosticsDomain(str, Enum):
    """Diagnostics categories available through the editor facade."""

    RENDER = "render"
    CACHE = "cache"
    SWAP = "swap"
    MASK = "mask"
    EXECUTOR = "executor"
    RETRY = "retry"
    SAM = "sam"


class ControlMode(str, Enum):
    """Built-in control modes supported by the tool manager."""

    CURSOR = "cursor"
    PANZOOM = "panzoom"
    MOVE = "move"
    TRANSFORM = "transform"
    DRAW_BRUSH = "draw-brush"
    CLONE_STAMP = "clone-stamp"
    SMART_SELECT = "smart-select"
    SELECT_RECTANGLE = "select-rectangle"
    SELECT_ELLIPSE = "select-ellipse"
    SELECT_LASSO = "select-lasso"
    VECTOR_SHAPE = "vector-shape"
    VECTOR_PATH = "vector-path"
    VECTOR_NODE = "vector-node"
    VECTOR_TEXT = "vector-text"


class EditorCapability(str, Enum):
    """Identify independently host-configurable editor capabilities."""

    SELECT_PIXELS = "select-pixels"
    EDIT_PIXELS = "edit-pixels"
    PAINT = "paint"
    MOVE_LAYERS = "move-layers"
    TRANSFORM_LAYERS = "transform-layers"
    EDIT_VECTORS = "edit-vectors"
    MANAGE_LAYERS = "manage-layers"
    EDIT_RESOURCES = "edit-resources"


class EditorIntent(str, Enum):
    """Identify a public editor operation that can be queried before use."""

    SELECT_PIXELS = "select-pixels"
    DELETE_PIXELS = "delete-pixels"
    PAINT = "paint"
    MOVE = "move"
    TRANSFORM = "transform"


class PixelSelectionMode(str, Enum):
    """Control how incoming coverage combines with the active selection."""

    REPLACE = "replace"
    ADD = "add"
    SUBTRACT = "subtract"
    INTERSECT = "intersect"


class CoverageCoordinateSpace(str, Enum):
    """Interpret host-authored coverage in target units or normalized fractions."""

    TARGET = "target"
    NORMALIZED_TARGET = "normalized-target"


class PaintTargetKind(str, Enum):
    """Public paint destinations owned by the active composition."""

    LAYER = "layer"
    PIXEL_SELECTION = "pixel-selection"


class NonEditablePaintPolicy(str, Enum):
    """Choose how interactive painting handles a non-editable selected layer."""

    REJECT = "reject"
    CREATE_RASTER_LAYER = "create-raster-layer"


class FloatingPixelMode(str, Enum):
    """Control whether a floating edit cuts or copies its source pixels."""

    CUT = "cut"
    COPY = "copy"


class RasterExtentPolicy(str, Enum):
    """Control whether editor raster writes may enlarge local storage."""

    FIXED = "fixed"
    EXPAND_ON_WRITE = "expand-on-write"
    UNBOUNDED = "unbounded"


@dataclass(frozen=True, slots=True)
class CompositionPolicy:
    """Host-controlled structural permissions for one composition."""

    removable: bool = True


@dataclass(frozen=True, slots=True)
class CompositionEntry:
    """Public snapshot entry for one composition."""

    composition_id: uuid.UUID
    kind: str
    title: str
    scene_layer_count: int = 0
    scene_bounds: QRectF | None = None
    layers: tuple[CompositionLayerEntry, ...] = ()
    policy: CompositionPolicy = CompositionPolicy()

    def __post_init__(self) -> None:
        """Detach optional Qt geometry from composition snapshots."""
        if self.scene_bounds is not None:
            object.__setattr__(self, "scene_bounds", QRectF(self.scene_bounds))
        object.__setattr__(self, "layers", tuple(self.layers))


@dataclass(frozen=True, slots=True)
class CompositionSnapshot:
    """Public snapshot of composition browser state."""

    compositions: dict[uuid.UUID, CompositionEntry]
    order: tuple[uuid.UUID, ...]
    current_composition_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class CompositionLayerClip:
    """Public clip rectangle applied to a composed scene layer."""

    coordinate_space: str
    rect: QRectF

    def __post_init__(self) -> None:
        """Detach mutable Qt geometry from caller-owned clip state."""
        object.__setattr__(self, "rect", QRectF(self.rect))


@dataclass(frozen=True, slots=True)
class LayerPolicy:
    """Host-controlled permissions for direct scene-layer interaction."""

    selectable: bool = False
    movable: bool = False
    pixel_editable: bool = False
    reorderable: bool = True
    removable: bool = True


@dataclass(frozen=True, slots=True)
class EditorPolicy:
    """Compose the editor capabilities enabled by one host application."""

    capabilities: frozenset[EditorCapability] = field(
        default_factory=lambda: frozenset(EditorCapability)
    )
    noneditable_paint: NonEditablePaintPolicy = (
        NonEditablePaintPolicy.CREATE_RASTER_LAYER
    )

    def __post_init__(self) -> None:
        """Normalize caller values into one immutable editor policy."""
        object.__setattr__(
            self,
            "capabilities",
            frozenset(EditorCapability(value) for value in self.capabilities),
        )
        object.__setattr__(
            self,
            "noneditable_paint",
            NonEditablePaintPolicy(self.noneditable_paint),
        )


@dataclass(frozen=True, slots=True)
class EditorOperationState:
    """Describe whether one editor intent can execute against current state."""

    intent: EditorIntent
    allowed: bool
    denial: str | None
    alternatives: tuple[str, ...]
    scene_id: uuid.UUID | None
    layer_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class CompositionLayerEntry:
    """Detached browser metadata for one ordered composition layer."""

    layer_id: uuid.UUID
    source_kind: str
    source_id: uuid.UUID
    label: str | None
    role: str
    visible: bool
    opacity: float
    interaction: LayerPolicy
    transform: QTransform

    def __post_init__(self) -> None:
        """Detach mutable Qt transform state from the composition owner."""
        object.__setattr__(self, "transform", QTransform(self.transform))


@dataclass(frozen=True, slots=True)
class LayerSelectionSnapshot:
    """Public identity of the selected layer in the active scene."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class MoveToolOptions:
    """Public configuration for direct layer movement."""

    auto_select_layers: bool = True


@dataclass(frozen=True, slots=True)
class RasterSurfaceSnapshot:
    """Public raster storage state for one active scene layer."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    bounds: QRect
    extent_policy: RasterExtentPolicy
    content_revision: int
    structure_revision: int
    pending_request_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        """Detach mutable Qt bounds from the source domain."""
        object.__setattr__(self, "bounds", QRect(self.bounds))


@dataclass(frozen=True, slots=True)
class PixelSelectionSnapshot:
    """Public snapshot of the active composition's pixel selection."""

    scene_id: uuid.UUID
    revision: int
    bounds: QRect | None
    coverage: QImage | None

    def __post_init__(self) -> None:
        """Detach mutable Qt raster and geometry values."""
        if self.bounds is not None:
            object.__setattr__(self, "bounds", QRect(self.bounds))
        if self.coverage is not None:
            object.__setattr__(self, "coverage", self.coverage.copy())

    @property
    def has_selection(self) -> bool:
        """Return whether nonzero pixel-selection coverage is active."""
        return self.coverage is not None


@dataclass(frozen=True, slots=True)
class FloatingPixelSnapshot:
    """Public snapshot of one unresolved floating pixel edit."""

    scene_id: uuid.UUID
    source_layer_id: uuid.UUID
    mode: FloatingPixelMode
    offset: QPoint
    bounds: QRect | None

    def __post_init__(self) -> None:
        """Detach mutable Qt geometry from editor-owned state."""
        object.__setattr__(self, "offset", QPoint(self.offset))
        if self.bounds is not None:
            object.__setattr__(self, "bounds", QRect(self.bounds))


@dataclass(frozen=True, slots=True)
class LayerSnapshot:
    """One source-backed layer in a public composed scene."""

    layer_id: uuid.UUID
    source_kind: str
    source_id: uuid.UUID
    placement: QRectF
    visible: bool = True
    opacity: float = 1.0
    tint: QColor | None = None
    clip: CompositionLayerClip | None = None
    hit_test: bool = True
    role: str = "content"
    metadata: Mapping[str, object] = field(default_factory=dict)
    interaction: LayerPolicy = LayerPolicy()
    label: str | None = None
    transform: QTransform = field(default_factory=QTransform)

    def __post_init__(self) -> None:
        """Normalize mutable public layer inputs into QPane-owned values."""
        object.__setattr__(self, "placement", QRectF(self.placement))
        object.__setattr__(self, "transform", QTransform(self.transform))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        if self.tint is not None:
            object.__setattr__(self, "tint", QColor(self.tint))


@dataclass(frozen=True, slots=True)
class PlacedAssetSnapshot:
    """Detached provenance and availability state for one placed layer."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    asset_id: uuid.UUID
    mode: PlacedAssetMode
    status: PlacedAssetStatus
    source_path: Path | None
    error: str | None
    keep_fallback: bool
    content_revision: int
    generation: int


@dataclass(frozen=True, slots=True)
class PaintTargetSnapshot:
    """Detached identity and source kind for the active paint destination."""

    scene_id: uuid.UUID
    kind: PaintTargetKind
    layer_id: uuid.UUID | None
    source_kind: str | None


@dataclass(frozen=True, slots=True)
class SceneSnapshot:
    """Normalized public snapshot for the active renderable composition."""

    composition_id: uuid.UUID
    scene_id: uuid.UUID
    title: str
    bounds: QRectF
    layers: tuple[LayerSnapshot, ...]

    def __post_init__(self) -> None:
        """Detach mutable Qt geometry and normalize layer storage."""
        object.__setattr__(self, "bounds", QRectF(self.bounds))
        object.__setattr__(self, "layers", tuple(self.layers))


@dataclass(frozen=True, slots=True)
class LayerHit:
    """Public hit-test result for a project-resource layer."""

    composition_id: uuid.UUID
    scene_id: uuid.UUID
    layer_id: uuid.UUID
    source_id: uuid.UUID
    role: str
    metadata: Mapping[str, object]
    panel_point: QPointF
    scene_point: QPointF
    source_point: QPointF

    def __post_init__(self) -> None:
        """Detach mutable Qt values and protect metadata from mutation."""
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        object.__setattr__(self, "panel_point", QPointF(self.panel_point))
        object.__setattr__(self, "scene_point", QPointF(self.scene_point))
        object.__setattr__(self, "source_point", QPointF(self.source_point))
