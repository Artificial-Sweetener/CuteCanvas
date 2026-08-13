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

"""Prove exact Coverage8 affine evaluation through the Python facade."""

from __future__ import annotations

from ferrastra import (
    CompiledGraph,
    CoverageResult,
    Engine,
    EvaluationBudget,
    GraphBuilder,
    Region,
)


def test_python_coverage_affine_preserves_scalar_range_and_product_type() -> None:
    """Publish scalar samples without introducing raster color semantics."""
    engine, compiled = _compiled_graph(bytes((0, 64, 128, 255)))
    region = Region(0, 0, 3, 3)
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

    assert isinstance(result, CoverageResult)
    assert result.format == "coverage8"
    assert (result.width, result.height, result.stride_bytes) == (3, 3, 3)
    assert result.pixels == bytes((0, 32, 64, 64, 112, 160, 128, 192, 255))


def test_python_coverage_affine_tiles_equal_the_monolithic_product() -> None:
    """Keep destination phase stable across regional coverage evaluation."""
    engine, compiled = _compiled_graph(bytes((0, 64, 128, 255)))
    budget = EvaluationBudget(memory_bytes=1_048_576, scratch_bytes=1_048_576)
    complete = engine.evaluate(compiled, "result", Region(0, 0, 3, 3), budget).pixels
    top = engine.evaluate(compiled, "result", Region(0, 0, 3, 1), budget).pixels
    bottom = engine.evaluate(compiled, "result", Region(0, 1, 3, 2), budget).pixels

    assert top + bottom == complete


def test_python_coverage_area_reduction_matches_independent_block_averages() -> None:
    """Reduce aligned integer footprints with exact range-preserving averages."""
    source = bytes(
        (
            0,
            10,
            80,
            100,
            20,
            30,
            120,
            140,
            160,
            180,
            220,
            240,
            200,
            220,
            240,
            255,
        )
    )
    engine, compiled = _compiled_graph(
        source,
        source_width=4,
        source_height=4,
        destination_width=2,
        destination_height=2,
        scale=2.0,
        translation=0.5,
        filter_name="area",
    )

    result = engine.evaluate(
        compiled,
        "result",
        Region(0, 0, 2, 2),
        EvaluationBudget(memory_bytes=1_048_576, scratch_bytes=1_048_576),
    )

    assert result.pixels == bytes((15, 110, 190, 239))


def _compiled_graph(
    source: bytes,
    *,
    source_width: int = 2,
    source_height: int = 2,
    destination_width: int = 3,
    destination_height: int = 3,
    scale: float = 0.5,
    translation: float = 0.0,
    filter_name: str = "linear",
) -> tuple[Engine, CompiledGraph]:
    """Construct a small coverage graph using only public typed contracts."""
    engine = Engine()
    revision = engine.add_coverage8(source, source_width, source_height)
    builder = GraphBuilder(1)
    builder.add_node(1, "ferrastra.source.coverage")
    builder.set_source_revision(1, revision)
    builder.add_node(2, "ferrastra.resample.coverage-affine")
    builder.connect(1, "result", 2, "source")
    for parameter, value in (
        ("source_width", source_width),
        ("source_height", source_height),
        ("destination_width", destination_width),
        ("destination_height", destination_height),
    ):
        builder.set_integer(2, parameter, value)
    for parameter, value in (
        ("source_m11", scale),
        ("source_m12", 0.0),
        ("source_m21", 0.0),
        ("source_m22", scale),
        ("source_tx", translation),
        ("source_ty", translation),
    ):
        builder.set_scalar(2, parameter, value)
    builder.set_enum(2, "filter", filter_name)
    builder.add_output("result", 2)
    return engine, engine.compile(builder.build())
