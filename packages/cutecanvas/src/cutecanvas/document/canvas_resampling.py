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
"""Revision-guarded coordination of whole-canvas resampling products."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from enum import Enum
from math import ceil, floor

from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QImage
from qpane.sdk.execution import CancellationToken
from qpane.sdk.scene import (
    ClipCoordinateSpace,
    LayerClip,
    LayerTransform,
    RasterBounds,
)

from ..composition.geometry_policy import LayerGeometryMode, LayerGeometryPolicy
from ..composition.layers import CompositionLayerInstance
from ..composition.resource_lifetime import ResourceLeaseKind
from ..coverage import CoverageAssetSnapshot, CoverageSnapshot
from ..coverage.document import CoverageDocument
from ..masks.mask import MaskAssetStore
from ..placed.model import PlacedAssetSnapshot
from ..raster.sparse_grid import SparseRasterSnapshot
from ..resources import ProjectResourceKind, ProjectResourceReference
from ..resources.document_core import DocumentResourceCore
from ..selection import PixelSelectionService
from ..vector.effects import VectorMaskEffect
from .canvas_crop import scaled_canvas_crop_effect
from .canvas_geometry import (
    CanvasGeometryEdit,
    CanvasGeometryState,
    CanvasGeometryStateOwner,
    scaled_raster_bounds,
)


class CanvasResamplingMode(str, Enum):
    """Select the Qt-backed pixel transformation quality policy."""

    FAST = "fast"
    SMOOTH = "smooth"


@dataclass(frozen=True, slots=True)
class CanvasResampleResourceInput:
    """Capture one raster-bearing resource without live-store access."""

    source_id: uuid.UUID
    target_id: uuid.UUID
    kind: ProjectResourceKind
    revision: int
    payload: SparseRasterSnapshot | PlacedAssetSnapshot | CoverageAssetSnapshot


@dataclass(frozen=True, slots=True)
class CanvasResampleResourceProduct:
    """Carry one detached replacement payload to owner-thread adoption."""

    source_id: uuid.UUID
    target_id: uuid.UUID
    kind: ProjectResourceKind
    payload: SparseRasterSnapshot | QImage | CoverageAssetSnapshot


@dataclass(frozen=True, slots=True)
class CanvasResamplePlan:
    """Describe one immutable revision-guarded resampling request."""

    composition_id: uuid.UUID
    before: CanvasGeometryState
    selection_revision: int
    target_bounds: QRectF
    target_size: QSize
    mode: CanvasResamplingMode
    local_scale: LayerTransform
    scene_scale: LayerTransform
    after_layers: tuple[CompositionLayerInstance, ...]
    resources: tuple[CanvasResampleResourceInput, ...]
    estimated_retained_bytes: int

    def __post_init__(self) -> None:
        """Detach mutable Qt values retained across worker execution."""
        object.__setattr__(self, "target_bounds", QRectF(self.target_bounds))
        object.__setattr__(self, "target_size", QSize(self.target_size))


@dataclass(frozen=True, slots=True)
class CanvasResampleProduct:
    """Return every computed payload and selection projection together."""

    plan: CanvasResamplePlan
    resources: tuple[CanvasResampleResourceProduct, ...]
    selection_document: CoverageDocument | None
    selection_coverage: CoverageSnapshot | None


class CanvasResamplingOwner:
    """Capture and atomically adopt source-aware canvas resampling."""

    def __init__(
        self,
        *,
        document: DocumentResourceCore,
        masks: MaskAssetStore,
        state: CanvasGeometryStateOwner,
        selections: PixelSelectionService,
    ) -> None:
        """Bind durable payload, geometry, history, and selection owners."""
        self._document = document
        self._masks = masks
        self._state = state
        self._selections = selections
        from .canvas_resample_resources import CanvasResampleResourceOwner

        self._resources = CanvasResampleResourceOwner(document, masks)

    def capture(
        self,
        composition_id: uuid.UUID,
        size: QSize,
        *,
        mode: CanvasResamplingMode,
    ) -> CanvasResamplePlan:
        """Capture one current composition for worker-side resampling."""
        target_size = _validated_size(size)
        resolved_mode = CanvasResamplingMode(mode)
        before = self._state.capture(composition_id)
        old_width, old_height = _pixel_size(before.bounds)
        scale_x = target_size.width() / old_width
        scale_y = target_size.height() / old_height
        local_scale = LayerTransform(m11=scale_x, m22=scale_y)
        scene_scale = LayerTransform(
            m11=scale_x,
            m22=scale_y,
            dx=before.bounds.x() * (1.0 - scale_x),
            dy=before.bounds.y() * (1.0 - scale_y),
        )
        target_bounds = QRectF(
            before.bounds.x(),
            before.bounds.y(),
            float(target_size.width()),
            float(target_size.height()),
        )
        resources, replacements, estimate = self._resources.capture(
            before.layers,
            local_scale,
        )
        estimate += _selection_retained_bytes(before.selection_coverage, scene_scale)
        after_layers = tuple(
            _scaled_layer(
                layer,
                replacements=replacements,
                local_scale=local_scale,
                scene_scale=scene_scale,
            )
            for layer in before.layers
        )
        return CanvasResamplePlan(
            composition_id,
            before,
            self._selections.state(composition_id).revision,
            target_bounds,
            target_size,
            resolved_mode,
            local_scale,
            scene_scale,
            after_layers,
            resources,
            estimate,
        )

    @staticmethod
    def build(
        plan: CanvasResamplePlan,
        cancellation: CancellationToken | None = None,
    ) -> CanvasResampleProduct:
        """Compute all raster products without consulting live document state."""
        from .canvas_resample_products import build_resample_product

        return build_resample_product(plan, cancellation)

    def commit(self, product: CanvasResampleProduct) -> bool:
        """Adopt one current complete product as a single history edit."""
        plan = product.plan
        if not self._is_current(plan):
            return False
        installed: list[CanvasResampleResourceProduct] = []
        restored = False
        try:
            for item in product.resources:
                self._resources.install(item)
                installed.append(item)
            after = CanvasGeometryState(
                plan.target_bounds,
                plan.after_layers,
                product.selection_document,
                product.selection_coverage,
            )
            command = CanvasGeometryEdit(
                plan.composition_id,
                plan.before,
                after,
                plan.estimated_retained_bytes,
            )
            lifetime = self._document.compositions.resource_lifetime
            for source in command.retained_resources:
                lifetime.acquire(source, ResourceLeaseKind.SESSION)
            try:
                restored = self._state.restore(plan.composition_id, after)
                if restored:
                    try:
                        self._document.compositions.edit_controller.record_applied(
                            command
                        )
                    except Exception:
                        self._state.restore(plan.composition_id, plan.before)
                        restored = False
                        raise
            finally:
                for source in command.retained_resources:
                    lifetime.release(source, ResourceLeaseKind.SESSION)
            if not restored:
                self._resources.discard(tuple(installed))
                return False
            return True
        except Exception:
            if restored:
                self._state.restore(plan.composition_id, plan.before)
            self._resources.discard(tuple(installed))
            raise

    def _is_current(self, plan: CanvasResamplePlan) -> bool:
        """Return whether every captured document and resource revision remains live."""
        current = self._state.capture(plan.composition_id)
        if (
            current.bounds != plan.before.bounds
            or current.layers != plan.before.layers
            or self._selections.state(plan.composition_id).revision
            != plan.selection_revision
        ):
            return False
        return self._resources.revisions_match(plan.resources)


def _scaled_layer(
    layer: CompositionLayerInstance,
    *,
    replacements: dict[uuid.UUID, uuid.UUID],
    local_scale: LayerTransform,
    scene_scale: LayerTransform,
) -> CompositionLayerInstance:
    """Scale one instance while compensating physically resized local storage."""
    source = layer.source
    source_id = (
        source.resource_id if isinstance(source, ProjectResourceReference) else None
    )
    replacement_id = None if source_id is None else replacements.get(source_id)
    if replacement_id is None:
        return replace(
            layer,
            transform=layer.transform.followed_by(scene_scale),
            clip=_scaled_scene_clip(layer.clip, scene_scale),
        )
    inverse = local_scale.inverted()
    assert inverse is not None
    return replace(
        layer,
        source=ProjectResourceReference(replacement_id),
        transform=inverse.followed_by(layer.transform).followed_by(scene_scale),
        clip=_scaled_scene_clip(layer.clip, scene_scale),
        effects=tuple(
            _scaled_local_effect(effect, local_scale) for effect in layer.effects
        ),
        geometry=_scaled_geometry(layer.geometry, local_scale),
    )


def _scaled_local_effect(effect: object, scale: LayerTransform) -> object:
    """Scale target-local vector-mask geometry with resized raster storage."""
    if isinstance(effect, VectorMaskEffect):
        return replace(effect, transform=effect.transform.followed_by(scale))
    return scaled_canvas_crop_effect(effect, scale)


def _scaled_geometry(
    policy: LayerGeometryPolicy,
    scale: LayerTransform,
) -> LayerGeometryPolicy:
    """Scale explicit source-local manipulation bounds when present."""
    if policy.mode is not LayerGeometryMode.CUSTOM or policy.custom_bounds is None:
        return policy
    return LayerGeometryPolicy(
        LayerGeometryMode.CUSTOM,
        scaled_raster_bounds(policy.custom_bounds, scale),
    )


def _scaled_scene_clip(
    clip: LayerClip | None,
    scale: LayerTransform,
) -> LayerClip | None:
    """Scale explicit scene-coordinate clips with the document geometry."""
    if clip is None or clip.coordinate_space is not ClipCoordinateSpace.SCENE:
        return clip
    rect = scale.map_rect(QRectF(clip.x, clip.y, clip.width, clip.height))
    return LayerClip(
        clip.coordinate_space,
        rect.x(),
        rect.y(),
        rect.width(),
        rect.height(),
    )


def _validated_size(size: QSize) -> QSize:
    """Return a detached positive target size."""
    if not isinstance(size, QSize):
        raise TypeError("size must be a QSize")
    target = QSize(size)
    if target.width() <= 0 or target.height() <= 0:
        raise ValueError("canvas dimensions must be positive")
    return target


def _pixel_size(bounds: QRectF) -> tuple[int, int]:
    """Return whole-pixel dimensions for resampling geometry."""
    width = round(bounds.width())
    height = round(bounds.height())
    if bounds.width() != float(width) or bounds.height() != float(height):
        raise ValueError("canvas bounds must have whole-pixel dimensions")
    return width, height


def _selection_retained_bytes(
    selection: CoverageSnapshot | None,
    scale: LayerTransform,
) -> int:
    """Estimate detached selection input and output held during execution."""
    if selection is None or selection.bounds is None:
        return 0
    source_bytes = selection.pixels.nbytes
    target = _mapped_selection_size(selection.bounds, scale)
    return source_bytes + target.width() * target.height()


def _mapped_selection_size(bounds: RasterBounds, scale: LayerTransform) -> QSize:
    """Return the integer envelope dimensions of scaled selection coverage."""
    rectangle = scale.map_rect(QRectF(bounds.to_qrect()))
    return QSize(
        max(1, ceil(rectangle.right()) - floor(rectangle.left())),
        max(1, ceil(rectangle.bottom()) - floor(rectangle.top())),
    )


__all__ = [
    "CanvasResamplePlan",
    "CanvasResampleProduct",
    "CanvasResamplingMode",
    "CanvasResamplingOwner",
]
