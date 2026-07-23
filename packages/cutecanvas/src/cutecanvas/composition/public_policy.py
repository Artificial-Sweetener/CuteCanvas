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
"""Translate host policy values at the composition boundary."""

from __future__ import annotations

from qpane.sdk.scene import LayerInteractionPolicy

from ..types import CompositionPolicy, LayerPolicy
from .model import CompositionDocumentPolicy


def internal_layer_policy(
    policy: LayerPolicy,
) -> LayerInteractionPolicy:
    """Convert validated host layer permissions to domain policy."""
    if not isinstance(policy, LayerPolicy):
        raise TypeError("layer interaction must be LayerPolicy")
    return LayerInteractionPolicy(
        selectable=bool(policy.selectable),
        movable=bool(policy.movable),
        pixel_editable=bool(policy.pixel_editable),
        reorderable=bool(policy.reorderable),
        removable=bool(policy.removable),
    )


def public_layer_policy(
    policy: LayerInteractionPolicy,
) -> LayerPolicy:
    """Detach domain layer permissions for host snapshots."""
    return LayerPolicy(
        selectable=policy.selectable,
        movable=policy.movable,
        pixel_editable=policy.pixel_editable,
        reorderable=policy.reorderable,
        removable=policy.removable,
    )


def internal_document_policy(
    policy: CompositionPolicy,
    *,
    remove_if_catalog_resource_missing: bool = False,
) -> CompositionDocumentPolicy:
    """Convert validated host document permissions to domain policy."""
    if not isinstance(policy, CompositionPolicy):
        raise TypeError("policy must be CompositionPolicy")
    return CompositionDocumentPolicy(
        removable=bool(policy.removable),
        comparison_enabled=bool(policy.comparison_enabled),
        remove_if_catalog_resource_missing=remove_if_catalog_resource_missing,
    )


def public_document_policy(
    policy: CompositionDocumentPolicy,
) -> CompositionPolicy:
    """Detach host-visible document permissions from domain policy."""
    return CompositionPolicy(
        removable=policy.removable,
        comparison_enabled=policy.comparison_enabled,
    )
