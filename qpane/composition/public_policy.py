#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Translate host policy values at the composition boundary."""

from __future__ import annotations

from ..scene.model import LayerInteractionPolicy
from ..types import QPaneCompositionPolicy, QPaneLayerInteractionPolicy
from .model import CompositionDocumentPolicy


def internal_layer_policy(
    policy: QPaneLayerInteractionPolicy,
) -> LayerInteractionPolicy:
    """Convert validated host layer permissions to domain policy."""
    if not isinstance(policy, QPaneLayerInteractionPolicy):
        raise TypeError("layer interaction must be QPaneLayerInteractionPolicy")
    return LayerInteractionPolicy(
        selectable=bool(policy.selectable),
        movable=bool(policy.movable),
        pixel_editable=bool(policy.pixel_editable),
        reorderable=bool(policy.reorderable),
        removable=bool(policy.removable),
    )


def public_layer_policy(
    policy: LayerInteractionPolicy,
) -> QPaneLayerInteractionPolicy:
    """Detach domain layer permissions for host snapshots."""
    return QPaneLayerInteractionPolicy(
        selectable=policy.selectable,
        movable=policy.movable,
        pixel_editable=policy.pixel_editable,
        reorderable=policy.reorderable,
        removable=policy.removable,
    )


def internal_document_policy(
    policy: QPaneCompositionPolicy,
    *,
    remove_if_catalog_resource_missing: bool = False,
) -> CompositionDocumentPolicy:
    """Convert validated host document permissions to domain policy."""
    if not isinstance(policy, QPaneCompositionPolicy):
        raise TypeError("policy must be QPaneCompositionPolicy")
    return CompositionDocumentPolicy(
        removable=bool(policy.removable),
        comparison_enabled=bool(policy.comparison_enabled),
        remove_if_catalog_resource_missing=remove_if_catalog_resource_missing,
    )


def public_document_policy(
    policy: CompositionDocumentPolicy,
) -> QPaneCompositionPolicy:
    """Detach host-visible document permissions from domain policy."""
    return QPaneCompositionPolicy(
        removable=policy.removable,
        comparison_enabled=policy.comparison_enabled,
    )
