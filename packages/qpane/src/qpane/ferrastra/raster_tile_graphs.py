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

"""Construct canonical native graphs for QPane raster tile requests."""

from __future__ import annotations

from ferrastra import Graph, GraphBuilder, RasterReconstructionSpace
from qpane.scene.raster_sampling import RasterExactSampling


def sampled_view_graph(
    revision: str,
    source_size: tuple[int, int],
    destination_size: tuple[int, int],
    *,
    source_center: tuple[float, float],
    source_step: tuple[float, float],
    sampling: RasterExactSampling,
    reconstruction_space: RasterReconstructionSpace = (
        RasterReconstructionSpace.SRGB_ENCODED
    ),
) -> Graph:
    """Build the selected exact axis-aligned graph for a raster tile."""
    builder = GraphBuilder(1)
    builder.add_node(1, "ferrastra.source.raster")
    builder.set_source_revision(1, revision)
    operation = {
        RasterExactSampling.NEAREST: "ferrastra.resample.affine-nearest",
        RasterExactSampling.LANCZOS3: "ferrastra.resample.lanczos3-view",
    }.get(sampling)
    if operation is None:
        raise ValueError("axis-aligned tiles require nearest or Lanczos3 sampling")
    builder.add_node(2, operation)
    builder.connect(1, "result", 2, "source")
    _set_dimensions(builder, source_size, destination_size)
    if sampling is RasterExactSampling.NEAREST:
        _set_affine_matrix(
            builder,
            (
                source_step[0],
                0.0,
                0.0,
                source_step[1],
                source_center[0],
                source_center[1],
            ),
        )
        builder.set_enum(2, "edge_mode", "clamp")
    else:
        for parameter, value in (
            ("source_center_x", source_center[0]),
            ("source_center_y", source_center[1]),
            ("source_step_x", source_step[0]),
            ("source_step_y", source_step[1]),
        ):
            builder.set_scalar(2, parameter, value)
        builder.set_enum(2, "edge_mode", "clamp")
        builder.set_enum(2, "working_space", reconstruction_space.value)
    builder.add_output("result", 2)
    return builder.build()


def affine_graph(
    revision: str,
    source_size: tuple[int, int],
    destination_size: tuple[int, int],
    *,
    matrix: tuple[float, float, float, float, float, float],
    sampling: RasterExactSampling,
    reconstruction_space: RasterReconstructionSpace = (
        RasterReconstructionSpace.SRGB_ENCODED
    ),
) -> Graph:
    """Build the selected exact affine graph for a physical panel tile."""
    builder = GraphBuilder(1)
    builder.add_node(1, "ferrastra.source.raster")
    builder.set_source_revision(1, revision)
    operation = {
        RasterExactSampling.NEAREST: "ferrastra.resample.affine-nearest",
        RasterExactSampling.AFFINE_BILINEAR: "ferrastra.resample.affine-bilinear",
    }.get(sampling)
    if operation is None:
        raise ValueError("affine tiles require nearest or affine bilinear sampling")
    builder.add_node(2, operation)
    builder.connect(1, "result", 2, "source")
    _set_dimensions(builder, source_size, destination_size)
    _set_affine_matrix(builder, matrix)
    builder.set_enum(2, "edge_mode", "clamp")
    if sampling is RasterExactSampling.AFFINE_BILINEAR:
        builder.set_enum(2, "working_space", reconstruction_space.value)
    builder.add_output("result", 2)
    return builder.build()


def _set_affine_matrix(
    builder: GraphBuilder,
    matrix: tuple[float, float, float, float, float, float],
) -> None:
    """Set one output-to-source affine transform on node two."""
    for parameter, value in zip(
        (
            "source_m11",
            "source_m12",
            "source_m21",
            "source_m22",
            "source_tx",
            "source_ty",
        ),
        matrix,
        strict=True,
    ):
        builder.set_scalar(2, parameter, value)


def _set_dimensions(
    builder: GraphBuilder,
    source_size: tuple[int, int],
    destination_size: tuple[int, int],
) -> None:
    """Set the shared explicit source and destination dimensions."""
    for parameter, value in (
        ("source_width", source_size[0]),
        ("source_height", source_size[1]),
        ("destination_width", destination_size[0]),
        ("destination_height", destination_size[1]),
    ):
        builder.set_integer(2, parameter, value)


__all__ = ["affine_graph", "sampled_view_graph"]
