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

"""Compile whole-raster scaling into canonical reconstruction graphs."""

from __future__ import annotations

from ferrastra import Graph, GraphBuilder


def build_lanczos3_scale_graph(
    revision: str,
    source_size: tuple[int, int],
    destination_size: tuple[int, int],
) -> Graph:
    """Return one exact whole-source Lanczos3 graph with clamped edges."""
    builder = GraphBuilder(1)
    builder.add_node(1, "ferrastra.source.raster")
    builder.set_source_revision(1, revision)
    builder.add_node(2, "ferrastra.resample.lanczos3")
    builder.connect(1, "result", 2, "source")
    for parameter, value in (
        ("source_width", source_size[0]),
        ("source_height", source_size[1]),
        ("destination_width", destination_size[0]),
        ("destination_height", destination_size[1]),
    ):
        builder.set_integer(2, parameter, value)
    builder.set_enum(2, "edge_mode", "clamp")
    builder.set_enum(2, "working_space", "srgb_linear")
    builder.add_output("result", 2)
    return builder.build()


__all__ = ["build_lanczos3_scale_graph"]
