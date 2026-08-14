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

"""Independent Python-boundary proof for affine bilinear edge sampling."""

from __future__ import annotations

from ferrastra import Engine, EvaluationBudget, GraphBuilder, Region


def test_affine_bilinear_clamp_keeps_opaque_boundary_samples() -> None:
    """Clamp mode reconstructs the edge without transparent contributions."""
    engine = Engine()
    source = bytes((255, 0, 0, 255, 0, 0, 255, 255))
    revision = engine.add_rgba8(source, 2, 1)
    builder = GraphBuilder(1)
    builder.add_node(1, "ferrastra.source.raster")
    builder.set_source_revision(1, revision)
    builder.add_node(2, "ferrastra.resample.affine-bilinear")
    builder.connect(1, "result", 2, "source")
    for parameter, value in (
        ("source_width", 2),
        ("source_height", 1),
        ("destination_width", 3),
        ("destination_height", 1),
    ):
        builder.set_integer(2, parameter, value)
    for parameter, value in (
        ("source_m11", 2.0 / 3.0),
        ("source_m12", 0.0),
        ("source_m21", 0.0),
        ("source_m22", 1.0),
        ("source_tx", -1.0 / 6.0),
        ("source_ty", 0.0),
    ):
        builder.set_scalar(2, parameter, value)
    builder.set_enum(2, "edge_mode", "clamp")
    builder.set_enum(2, "working_space", "srgb_encoded")
    builder.add_output("result", 2)
    compiled = engine.compile(builder.build())
    region = Region(0, 0, 3, 1)
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

    assert result.pixels[:4] == bytes((255, 0, 0, 255))
    assert result.pixels[-4:] == bytes((0, 0, 255, 255))
    assert result.pixels[3::4] == bytes((255, 255, 255))
