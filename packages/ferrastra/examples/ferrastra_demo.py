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
"""Evaluate canonical raster and coverage resampling through public APIs."""

from __future__ import annotations

from ferrastra import CoverageResult, Engine, EvaluationBudget, GraphBuilder, Region


def main() -> None:
    """Build, compile, and evaluate one exact resized raster graph."""
    engine = Engine()
    source_pixel = bytes((12, 24, 36, 255))
    revision = engine.add_rgba8(source_pixel * 4, 2, 2)
    builder = GraphBuilder(1)
    builder.add_node(1, "ferrastra.source.raster")
    builder.set_source_revision(1, revision)
    builder.add_node(2, "ferrastra.resample.lanczos3")
    builder.connect(1, "result", 2, "source")
    builder.set_integer(2, "source_width", 2)
    builder.set_integer(2, "source_height", 2)
    builder.set_integer(2, "destination_width", 5)
    builder.set_integer(2, "destination_height", 3)
    builder.add_output("result", 2)
    graph = builder.build()
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
    print(f"graph={graph.content_id}")
    print(f"product={result.product_id}")
    print(
        f"region={result.width}x{result.height}, peak={result.peak_memory_bytes} bytes"
    )
    print(result.pixels.hex())

    coverage_revision = engine.add_coverage8(bytes((0, 64, 128, 255)), 2, 2)
    coverage_builder = GraphBuilder(2)
    coverage_builder.add_node(1, "ferrastra.source.coverage")
    coverage_builder.set_source_revision(1, coverage_revision)
    coverage_builder.add_node(2, "ferrastra.resample.coverage-affine")
    coverage_builder.connect(1, "result", 2, "source")
    for parameter, value in (
        ("source_width", 2),
        ("source_height", 2),
        ("destination_width", 3),
        ("destination_height", 3),
    ):
        coverage_builder.set_integer(2, parameter, value)
    coverage_builder.set_scalar(2, "source_m11", 0.5)
    coverage_builder.set_scalar(2, "source_m22", 0.5)
    coverage_builder.add_output("result", 2)
    coverage_graph = coverage_builder.build()
    coverage_compiled = engine.compile(coverage_graph)
    coverage_region = Region(0, 0, 3, 3)
    coverage_requirements = engine.requirements(
        coverage_compiled,
        "result",
        coverage_region,
    )
    coverage = engine.evaluate(
        coverage_compiled,
        "result",
        coverage_region,
        EvaluationBudget(
            memory_bytes=coverage_requirements.memory_bytes,
            scratch_bytes=coverage_requirements.scratch_bytes,
        ),
    )
    if not isinstance(coverage, CoverageResult):
        raise TypeError("coverage graph published a non-coverage product")
    print(f"coverage={coverage.width}x{coverage.height}: {coverage.pixels.hex()}")


if __name__ == "__main__":
    main()
