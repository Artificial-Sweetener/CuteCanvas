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

"""Independent Python-boundary proof for exact nearest affine sampling."""

from __future__ import annotations

from ferrastra import CompiledGraph, Engine, EvaluationBudget, GraphBuilder, Region

_SOURCE = bytes(
    channel for pixel in range(12) for channel in (pixel, pixel + 32, pixel + 64, 255)
)


def test_affine_nearest_matches_an_independent_coordinate_oracle() -> None:
    """Choose the nearest transparent-edge sample for every output center."""
    engine, compiled = _compiled_graph()
    actual = _evaluate(engine, compiled, Region(0, 0, 5, 4))

    expected = bytearray()
    for output_y in range(4):
        for output_x in range(5):
            source_x = round(0.7 * output_x - 0.2 * output_y + 0.35)
            source_y = round(0.15 * output_x + 0.8 * output_y - 0.4)
            if 0 <= source_x < 4 and 0 <= source_y < 3:
                offset = (source_y * 4 + source_x) * 4
                expected.extend(_SOURCE[offset : offset + 4])
            else:
                expected.extend((0, 0, 0, 0))

    assert actual == bytes(expected)


def test_affine_nearest_tiles_equal_the_monolithic_product() -> None:
    """Keep nearest selection phase stable across regional evaluation."""
    engine, compiled = _compiled_graph()
    complete = _evaluate(engine, compiled, Region(0, 0, 5, 4))
    top = _evaluate(engine, compiled, Region(0, 0, 5, 1))
    middle = _evaluate(engine, compiled, Region(0, 1, 5, 2))
    bottom = _evaluate(engine, compiled, Region(0, 3, 5, 1))

    assert top + middle + bottom == complete


def test_affine_nearest_clamps_samples_beyond_the_source_boundary() -> None:
    """Clamp mode repeats the nearest boundary pixel without transparent output."""
    engine, compiled = _compiled_graph(edge_mode="clamp")
    actual = _evaluate(engine, compiled, Region(0, 0, 5, 4))

    expected = bytearray()
    for output_y in range(4):
        for output_x in range(5):
            source_x = round(0.7 * output_x - 0.2 * output_y + 0.35)
            source_y = round(0.15 * output_x + 0.8 * output_y - 0.4)
            source_x = min(3, max(0, source_x))
            source_y = min(2, max(0, source_y))
            offset = (source_y * 4 + source_x) * 4
            expected.extend(_SOURCE[offset : offset + 4])

    assert actual == bytes(expected)


def _compiled_graph(*, edge_mode: str = "transparent") -> tuple[Engine, CompiledGraph]:
    """Compile the fixed affine fixture through public typed contracts."""
    engine = Engine()
    revision = engine.add_rgba8(_SOURCE, 4, 3)
    builder = GraphBuilder(1)
    builder.add_node(1, "ferrastra.source.raster")
    builder.set_source_revision(1, revision)
    builder.add_node(2, "ferrastra.resample.affine-nearest")
    builder.connect(1, "result", 2, "source")
    for parameter, value in (
        ("source_width", 4),
        ("source_height", 3),
        ("destination_width", 5),
        ("destination_height", 4),
    ):
        builder.set_integer(2, parameter, value)
    for parameter, value in (
        ("source_m11", 0.7),
        ("source_m12", 0.15),
        ("source_m21", -0.2),
        ("source_m22", 0.8),
        ("source_tx", 0.35),
        ("source_ty", -0.4),
    ):
        builder.set_scalar(2, parameter, value)
    builder.set_enum(2, "edge_mode", edge_mode)
    builder.add_output("result", 2)
    return engine, engine.compile(builder.build())


def _evaluate(engine: Engine, compiled: CompiledGraph, region: Region) -> bytes:
    """Evaluate one admitted exact region from the fixed graph."""
    requirements = engine.requirements(compiled, "result", region)
    return engine.evaluate(
        compiled,
        "result",
        region,
        EvaluationBudget(
            memory_bytes=requirements.memory_bytes,
            scratch_bytes=requirements.scratch_bytes,
        ),
    ).pixels
