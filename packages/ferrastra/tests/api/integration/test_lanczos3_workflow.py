#    Ferrastra - CPU-first native graphics product engine
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

"""Prove exact Lanczos3 graph construction and evaluation through the Python facade."""

from __future__ import annotations

from ferrastra import (
    Engine,
    EvaluationBudget,
    Graph,
    GraphBuilder,
    RasterResult,
    Region,
)


def test_python_lanczos3_graph_resizes_exact_uniform_pixels() -> None:
    """Evaluate the canonical operation without exposing native assembly details."""
    source_pixel = bytes((12, 24, 36, 255))
    engine, graph = _resize_graph(source_pixel * 4, (2, 2), (5, 3))
    compiled = engine.compile(graph)
    region = Region(0, 0, 5, 3)
    requirements = engine.requirements(compiled, "result", region)
    result = engine.evaluate(
        compiled,
        "result",
        region,
        EvaluationBudget(
            memory_bytes=requirements.memory_bytes,
            scratch_bytes=requirements.scratch_bytes,
        ),
    )

    assert isinstance(result, RasterResult)
    assert result.pixels == source_pixel * 15
    assert (result.width, result.height, result.stride_bytes) == (5, 3, 20)
    assert result.evaluated_nodes == 2
    assert result.produced_samples == 19
    assert result.peak_memory_bytes == requirements.memory_bytes


def test_python_lanczos3_tiles_equal_the_monolithic_product() -> None:
    """Keep global destination phase stable across independently requested Python tiles."""
    source = bytes(
        channel
        for alpha in (32, 96, 160, 224, 255, 192)
        for channel in (alpha // 4, alpha // 2, alpha, alpha)
    )
    engine, graph = _resize_graph(source, (3, 2), (7, 5), edge="reflect")
    compiled = engine.compile(graph)
    budget = EvaluationBudget(memory_bytes=2_097_152, scratch_bytes=1_048_576)
    complete = engine.evaluate(compiled, "result", Region(0, 0, 7, 5), budget).pixels
    top = engine.evaluate(compiled, "result", Region(0, 0, 7, 2), budget).pixels
    bottom = engine.evaluate(compiled, "result", Region(0, 2, 7, 3), budget).pixels

    assert top + bottom == complete


def _resize_graph(
    source: bytes,
    source_size: tuple[int, int],
    destination_size: tuple[int, int],
    *,
    edge: str = "clamp",
    working_space: str = "srgb_linear",
) -> tuple[Engine, Graph]:
    """Construct one source-to-resize graph using only supported Python contracts."""
    engine = Engine()
    revision = engine.add_rgba8(source, *source_size)
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
    builder.set_enum(2, "edge_mode", edge)
    builder.set_enum(2, "working_space", working_space)
    builder.add_output("result", 2)
    return engine, builder.build()
