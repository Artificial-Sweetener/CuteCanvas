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

"""Prove the public Python source-to-identity graph workflow."""

from __future__ import annotations

from pathlib import Path

import pytest
from ferrastra import (
    CancellationToken,
    Engine,
    EvaluationBudget,
    EvaluationError,
    Graph,
    GraphBuilder,
    GraphError,
    Region,
)

_EXPECTED_GRAPH_ID = "81b201371878e651173c79a00a6b56b54ab680c35ee30cb756ac6b995cfcdf69"


def test_python_construction_matches_the_canonical_graph_fixture() -> None:
    """Normalize equivalent Python construction to the canonical cross-language record."""
    engine, graph = _identity_graph()
    fixture = Path(__file__).parents[2] / "fixtures/phase1_identity_graph.json"
    expected = fixture.read_text(encoding="utf-8").strip()

    assert graph.content_id == _EXPECTED_GRAPH_ID
    assert graph.to_json() == expected
    assert Graph.from_json(expected).to_json() == expected
    assert engine.compile(graph).graph_content_id == _EXPECTED_GRAPH_ID


def test_regional_evaluation_is_exact_deterministic_and_bounded() -> None:
    """Return exact regional pixels with deterministic identity and explicit accounting."""
    engine, graph = _identity_graph()
    compiled = engine.compile(graph)
    region = Region(1, 1, 2, 2)
    budget = EvaluationBudget(memory_bytes=64)

    first = engine.evaluate(compiled, "result", region, budget)
    second = engine.evaluate(compiled, "result", region, budget)

    assert first.pixels == bytes(range(20, 28)) + bytes(range(36, 44))
    assert first.product_id == second.product_id
    assert first.graph_content_id == graph.content_id
    assert (first.width, first.height, first.stride_bytes) == (2, 2, 8)
    assert first.format == "rgba8-premultiplied-encoded"
    assert first.peak_memory_bytes == 32
    assert first.evaluated_nodes == 2
    assert first.produced_samples == 8


def test_rejected_or_cancelled_evaluation_publishes_no_result() -> None:
    """Reject insufficient memory and cancellation through the stable exception boundary."""
    engine, graph = _identity_graph()
    compiled = engine.compile(graph)
    region = Region(1, 1, 2, 2)

    with pytest.raises(EvaluationError, match="memory limit"):
        engine.evaluate(compiled, "result", region, EvaluationBudget(memory_bytes=31))

    cancellation = CancellationToken()
    cancellation.cancel()
    assert cancellation.is_cancelled
    with pytest.raises(EvaluationError, match="cancelled"):
        engine.evaluate(
            compiled,
            "result",
            region,
            EvaluationBudget(memory_bytes=64, cancellation=cancellation),
        )


def test_authoring_metadata_and_unknown_operations_keep_distinct_contracts() -> None:
    """Exclude labels from identity while retaining unavailable operations losslessly."""
    engine, graph = _identity_graph(label=None)
    labelled_engine, labelled = _identity_graph(label="Preview")

    assert labelled.content_id == graph.content_id
    assert labelled.to_json() != graph.to_json()
    region = Region(1, 1, 2, 2)
    budget = EvaluationBudget(memory_bytes=64)
    product = engine.evaluate(engine.compile(graph), "result", region, budget)
    labelled_product = labelled_engine.evaluate(
        labelled_engine.compile(labelled), "result", region, budget
    )
    assert labelled_product.product_id == product.product_id

    builder = GraphBuilder(1)
    builder.add_node(1, "ferrastra.unavailable.operation")
    builder.add_output("result", 1)
    unavailable = builder.build()
    restored = Graph.from_json(unavailable.to_json())

    assert restored.to_json() == unavailable.to_json()
    with pytest.raises(GraphError, match="validation"):
        Engine().compile(restored)


def _identity_graph(label: str | None = None) -> tuple[Engine, Graph]:
    """Construct the canonical Phase 1 graph through supported Python APIs."""
    engine = Engine()
    revision = engine.add_rgba8(bytes(range(64)), 4, 4)
    builder = GraphBuilder(1)
    builder.add_node(1, "ferrastra.source.raster")
    builder.set_source_revision(1, revision)
    builder.add_node(2, "ferrastra.core.identity")
    builder.connect(1, "result", 2, "source")
    builder.add_output("result", 2)
    builder.set_label(label)
    return engine, builder.build()
