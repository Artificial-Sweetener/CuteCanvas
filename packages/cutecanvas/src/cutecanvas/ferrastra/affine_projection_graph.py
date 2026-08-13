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

"""Compile authoring affine geometry into canonical sampling graph parameters."""

from __future__ import annotations

from ferrastra import Graph, GraphBuilder
from PySide6.QtCore import QPointF
from qpane.sdk.scene import LayerTransform, RasterBounds


def build_affine_projection_graph(
    revision: str,
    source_size: tuple[int, int],
    transform: LayerTransform,
    source_bounds: RasterBounds,
    destination_bounds: RasterBounds,
    *,
    source_operation: str,
    projection_operation: str,
    working_space: str | None = None,
    filter_mode: str | None = None,
    edge_mode: str | None = None,
) -> Graph:
    """Return an exact output-index-to-source-index affine graph."""
    destination_to_image = _destination_to_image(
        transform,
        source_bounds,
        destination_bounds,
    )
    source_tx = (
        0.5 * destination_to_image.m11
        + 0.5 * destination_to_image.m21
        + destination_to_image.dx
        - 0.5
    )
    source_ty = (
        0.5 * destination_to_image.m12
        + 0.5 * destination_to_image.m22
        + destination_to_image.dy
        - 0.5
    )
    builder = GraphBuilder(1)
    builder.add_node(1, source_operation)
    builder.set_source_revision(1, revision)
    builder.add_node(2, projection_operation)
    builder.connect(1, "result", 2, "source")
    for parameter, value in (
        ("source_width", source_size[0]),
        ("source_height", source_size[1]),
        ("destination_width", destination_bounds.width),
        ("destination_height", destination_bounds.height),
    ):
        builder.set_integer(2, parameter, value)
    for parameter, value in (
        ("source_m11", destination_to_image.m11),
        ("source_m12", destination_to_image.m12),
        ("source_m21", destination_to_image.m21),
        ("source_m22", destination_to_image.m22),
        ("source_tx", source_tx),
        ("source_ty", source_ty),
    ):
        builder.set_scalar(2, parameter, value)
    if working_space is not None:
        builder.set_enum(2, "working_space", working_space)
    if filter_mode is not None:
        builder.set_enum(2, "filter", filter_mode)
    if edge_mode is not None:
        builder.set_enum(2, "edge_mode", edge_mode)
    builder.add_output("result", 2)
    return builder.build()


def _destination_to_image(
    transform: LayerTransform,
    source_bounds: RasterBounds,
    destination_bounds: RasterBounds,
) -> LayerTransform:
    """Return the inverse mapping from destination storage to source storage."""
    mapped_origin = transform.map_point(
        QPointF(float(source_bounds.x), float(source_bounds.y))
    )
    image_to_destination = LayerTransform(
        m11=transform.m11,
        m12=transform.m12,
        m21=transform.m21,
        m22=transform.m22,
        dx=mapped_origin.x() - destination_bounds.x,
        dy=mapped_origin.y() - destination_bounds.y,
    )
    destination_to_image = image_to_destination.inverted()
    if destination_to_image is None:
        raise ValueError("affine projection requires an invertible transform")
    return destination_to_image


__all__ = ["build_affine_projection_graph"]
