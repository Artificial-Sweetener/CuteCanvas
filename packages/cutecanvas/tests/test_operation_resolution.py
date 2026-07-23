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
"""Contracts for source-neutral editor operation resolution."""

from __future__ import annotations

import uuid

import numpy as np
from cutecanvas import EditorCapability
from cutecanvas.coverage import CoverageSnapshot
from cutecanvas.editor.operation_resolution import (
    EditorOperation,
    EditorOperationAlternative,
    EditorOperationDenial,
    EditorOperationResolver,
    EditorOperationTarget,
    EditorSourceOperationRegistry,
    EditorSourceOperations,
)
from cutecanvas.painting.targets import PaintTargetRegistry
from cutecanvas.placed.source_reference import PlacedAssetReference
from cutecanvas.raster.source_reference import EditableRasterReference
from cutecanvas.scene.layer_selection import SceneLayerSelectionController
from cutecanvas.scene.mutations import SceneMutationCoordinator
from cutecanvas.scene.pixel_owners import LayerPixelOwnerRegistry
from cutecanvas.selection import PixelSelectionService
from cutecanvas.types import RasterExtentPolicy
from PySide6.QtCore import QPointF
from qpane.scene.affine import LayerTransform
from qpane.scene.model import (
    LayerContentCapabilities,
    LayerDescriptor,
    LayerInteractionPolicy,
    LayerKind,
    LayerPlacement,
    SceneDescriptor,
    SceneKind,
)
from qpane.scene.raster import RasterBounds


class _NoSelectedPixels:
    """Represent an active scene without movable selected-layer pixels."""

    def resolve_selected(self):
        """Return no selected-pixel target."""
        return

    def resolve_at(self, _scene_point):
        """Return no pointer-addressed selected-pixel target."""
        return


class _PaintOwner:
    """Advertise paint support for editable raster references."""

    @staticmethod
    def supports(target) -> bool:
        """Accept only editable color-raster layers."""
        return target.layer is not None and isinstance(
            target.layer.source, EditableRasterReference
        )


class _PixelOwner:
    """Advertise pixel-mutation support for editable raster references."""

    @staticmethod
    def supports_layer(_scene, layer) -> bool:
        """Accept only editable color-raster layers."""
        return isinstance(layer.source, EditableRasterReference)


def _resolver_fixture(
    *,
    placed: bool,
    pixel_editable: bool = True,
    with_selection: bool = False,
    allowed_capabilities: frozenset[EditorCapability] | None = None,
) -> tuple[EditorOperationResolver, uuid.UUID, uuid.UUID]:
    """Build one operation resolver around real selection and registry owners."""
    scene_id = uuid.uuid4()
    layer_id = uuid.uuid4()
    source = (
        PlacedAssetReference(uuid.uuid4())
        if placed
        else EditableRasterReference(uuid.uuid4())
    )
    placement = LayerPlacement(0.0, 0.0, 16.0, 16.0)
    layer = LayerDescriptor(
        scene_id=scene_id,
        layer_id=layer_id,
        kind=LayerKind.IMAGE if placed else LayerKind.RASTER,
        source=source,
        placement=placement,
        transform=LayerTransform.from_placement(
            RasterBounds(0, 0, 16, 16),
            placement,
        ),
        interaction=LayerInteractionPolicy(
            selectable=True,
            movable=True,
            pixel_editable=pixel_editable,
        ),
        capabilities=LayerContentCapabilities(raster_editable=not placed),
    )
    scene = SceneDescriptor(
        scene_id,
        SceneKind.EXPLICIT,
        LayerPlacement(0.0, 0.0, 16.0, 16.0),
        (layer,),
    )
    mutations = SceneMutationCoordinator(lambda: scene)
    layer_selection = SceneLayerSelectionController()
    assert layer_selection.select(scene_id, layer_id)
    pixel_selection = PixelSelectionService()
    if with_selection:
        assert pixel_selection.replace_with_raster(
            scene_id,
            CoverageSnapshot(
                RasterBounds(0, 0, 8, 8),
                RasterExtentPolicy.EXPAND_ON_WRITE,
                np.full((8, 8), 255, dtype=np.uint8),
            ),
        )
    paint_targets = PaintTargetRegistry()
    paint_targets.register(_PaintOwner())
    pixel_owners = LayerPixelOwnerRegistry()
    pixel_owners.register(_PixelOwner())
    source_operations = EditorSourceOperationRegistry()
    source_operations.register(
        PlacedAssetReference,
        EditorSourceOperations(rasterize=True, edit_contents=True),
    )
    resolver = EditorOperationResolver(
        active_scene=lambda: scene,
        scene_mutations=mutations,
        layer_selection=layer_selection,
        pixel_selection=pixel_selection,
        selected_pixels=_NoSelectedPixels(),
        floating_pixels_active=lambda: False,
        floating_pixels_can_begin=lambda _point: False,
        active_paint_target=lambda: None,
        default_paint_target_available=lambda: False,
        paint_targets=paint_targets,
        pixel_owners=pixel_owners,
        source_operations=source_operations,
        capability_allowed=(
            lambda _capability: (
                True
                if allowed_capabilities is None
                else _capability in allowed_capabilities
            )
        ),
    )
    return resolver, scene_id, layer_id


def test_placed_sources_deny_direct_paint_with_explicit_alternatives() -> None:
    """Immutable placed content must never silently paint or auto-rasterize."""
    resolver, scene_id, layer_id = _resolver_fixture(placed=True)

    resolution = resolver.resolve(EditorOperation.PAINT)

    assert not resolution.allowed
    assert resolution.scene_id == scene_id
    assert resolution.layer_id == layer_id
    assert resolution.denial is EditorOperationDenial.DIRECT_PIXEL_EDIT_UNSUPPORTED
    assert resolution.alternatives == (
        EditorOperationAlternative.EDIT_CONTENTS,
        EditorOperationAlternative.RASTERIZE,
        EditorOperationAlternative.NEW_RASTER_LAYER,
    )


def test_placed_sources_deny_selection_delete_without_mutating() -> None:
    """Delete must report immutable content even when coverage is selected."""
    resolver, _scene_id, _layer_id = _resolver_fixture(
        placed=True,
        with_selection=True,
    )

    resolution = resolver.resolve(EditorOperation.DELETE_PIXELS)

    assert not resolution.allowed
    assert resolution.denial is EditorOperationDenial.DIRECT_PIXEL_EDIT_UNSUPPORTED
    assert EditorOperationAlternative.RASTERIZE in resolution.alternatives


def test_host_policy_denies_supported_direct_pixel_edits() -> None:
    """Intrinsic edit support must remain subordinate to host policy."""
    resolver, _scene_id, _layer_id = _resolver_fixture(
        placed=False,
        pixel_editable=False,
        with_selection=True,
    )

    paint = resolver.resolve(EditorOperation.PAINT)
    delete = resolver.resolve(EditorOperation.DELETE_PIXELS)

    assert paint.denial is EditorOperationDenial.HOST_POLICY_DENIED
    assert delete.denial is EditorOperationDenial.HOST_POLICY_DENIED


def test_delete_requires_pixel_selection_before_mutation_routing() -> None:
    """Delete without scene selection coverage must be a stable denied intent."""
    resolver, _scene_id, _layer_id = _resolver_fixture(placed=False)

    resolution = resolver.resolve(EditorOperation.DELETE_PIXELS)

    assert not resolution.allowed
    assert resolution.denial is EditorOperationDenial.NO_PIXEL_SELECTION


def test_empty_selected_pixel_intersection_falls_through_to_whole_layer() -> None:
    """Geometric selection alone must not suppress ordinary layer movement."""
    resolver, scene_id, layer_id = _resolver_fixture(
        placed=False,
        with_selection=True,
    )

    resolution = resolver.resolve(
        EditorOperation.MOVE,
        scene_point=QPointF(4.0, 4.0),
        candidate_layer_id=layer_id,
    )

    assert resolution.allowed
    assert resolution.target is EditorOperationTarget.LAYER
    assert resolution.scene_id == scene_id
    assert resolution.layer_id == layer_id


def test_global_policy_is_independent_from_intrinsic_layer_capability() -> None:
    """A supported layer must retain stable host-policy denial per operation."""
    resolver, _scene_id, _layer_id = _resolver_fixture(
        placed=False,
        with_selection=True,
        allowed_capabilities=frozenset({EditorCapability.SELECT_PIXELS}),
    )

    assert resolver.resolve(EditorOperation.SELECT_PIXELS).allowed
    for operation in (
        EditorOperation.PAINT,
        EditorOperation.DELETE_PIXELS,
        EditorOperation.MOVE,
        EditorOperation.TRANSFORM,
    ):
        resolution = resolver.resolve(operation)
        assert not resolution.allowed
        assert resolution.denial is EditorOperationDenial.HOST_POLICY_DENIED
