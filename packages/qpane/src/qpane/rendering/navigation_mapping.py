#    QPane - High-performance PySide6 image viewer
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

"""Translate complete panel mappings for retained-frame navigation."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QPoint, QPointF
from PySide6.QtGui import QTransform

from ..scene.render_plan import SceneRenderItem
from .panel_mapping import PanelLayerMapping, PiecewisePanelMapping
from .raster_sampling import device_aligned_raster_transform


def translate_render_item(item: SceneRenderItem, delta: QPointF) -> SceneRenderItem:
    """Translate one immutable item in logical painter coordinates."""
    transform = item.transform
    if isinstance(transform, PiecewisePanelMapping):
        return replace(item, transform=transform.translated(delta))
    translated = QTransform(
        transform.m11(),
        transform.m12(),
        transform.m13(),
        transform.m21(),
        transform.m22(),
        transform.m23(),
        transform.dx() + delta.x(),
        transform.dy() + delta.y(),
        transform.m33(),
    )
    return replace(item, transform=translated)


def retained_mapping_delta(
    first: PanelLayerMapping,
    second: PanelLayerMapping,
    *,
    device_pixel_ratio: float,
) -> QPoint | None:
    """Return one physical translation shared by two complete mappings."""
    if isinstance(first, QTransform) and isinstance(second, QTransform):
        return _affine_physical_delta(
            first,
            second,
            device_pixel_ratio=device_pixel_ratio,
        )
    if not isinstance(first, PiecewisePanelMapping) or not isinstance(
        second, PiecewisePanelMapping
    ):
        return None
    if len(first.patches) != len(second.patches):
        return None
    shared_delta: QPoint | None = None
    for first_patch, second_patch in zip(
        first.patches,
        second.patches,
        strict=True,
    ):
        if first_patch.source != second_patch.source:
            return None
        patch_delta = _affine_physical_delta(
            first_patch.transform,
            second_patch.transform,
            device_pixel_ratio=device_pixel_ratio,
        )
        if patch_delta is None:
            return None
        if shared_delta is None:
            shared_delta = patch_delta
        elif patch_delta != shared_delta:
            return None
    return shared_delta


def _affine_physical_delta(
    first: QTransform,
    second: QTransform,
    *,
    device_pixel_ratio: float,
) -> QPoint | None:
    """Return an exact device translation when affine linear parts match."""
    if not _linear_transform_matches(first, second):
        return None
    first_aligned = device_aligned_raster_transform(first, device_pixel_ratio)
    second_aligned = device_aligned_raster_transform(second, device_pixel_ratio)
    return QPoint(
        round((second_aligned.m31() - first_aligned.m31()) * device_pixel_ratio),
        round((second_aligned.m32() - first_aligned.m32()) * device_pixel_ratio),
    )


def _linear_transform_matches(first: QTransform, second: QTransform) -> bool:
    """Return whether two affine transforms differ only in translation."""
    return (
        first.m11() == second.m11()
        and first.m12() == second.m12()
        and first.m13() == second.m13()
        and first.m21() == second.m21()
        and first.m22() == second.m22()
        and first.m23() == second.m23()
        and first.m33() == second.m33()
    )


__all__ = ["retained_mapping_delta", "translate_render_item"]
