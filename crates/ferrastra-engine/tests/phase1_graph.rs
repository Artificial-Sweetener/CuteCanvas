//    Ferrastra - CPU-first native graphics product engine
//    Copyright (C) 2025  Artificial Sweetener and contributors
//
//    This program is free software: you can redistribute it and/or modify
//    it under the terms of the GNU General Public License as published by
//    the Free Software Foundation, either version 3 of the License, or
//    (at your option) any later version.
//
//    This program is distributed in the hope that it will be useful,
//    but WITHOUT ANY WARRANTY; without even the implied warranty of
//    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
//    GNU General Public License for more details.
//
//    You should have received a copy of the GNU General Public License
//    along with this program.  If not, see <https://www.gnu.org/licenses/>.

//! Public contract proof for the first executable native graph.

use std::num::NonZeroUsize;

use ferrastra_core::{
    CancellationToken, ExecutionBudget, IntRect, IntSize, OperationIdentity, PortId, ProductFormat,
    ProductView, QualityTier, RasterFormat, SemanticOperationId, SemanticVersion,
};
use ferrastra_engine::Engine;
use ferrastra_graph::{
    GraphBuilder, GraphDefinition, GraphName, GraphRevisionId, GraphSchemaVersion, NodeId,
    NodeOutput,
};

#[test]
fn regional_source_identity_evaluation_returns_exact_pixels_and_damage() {
    let mut engine =
        Engine::new().unwrap_or_else(|error| unreachable!("valid engine rejected: {error}"));
    let source_bytes = std::array::from_fn::<_, 64, _>(|index| u8::try_from(index).unwrap_or(0));
    let revision = engine
        .add_raster(
            ProductView::new(
                &source_bytes,
                IntSize { width: 4, height: 4 },
                16,
                ProductFormat::Raster(RasterFormat::Rgba8PremultipliedEncoded),
            )
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}")),
        )
        .unwrap_or_else(|error| unreachable!("valid source rejected: {error}"));
    let graph = graph(revision);
    let compiled = engine
        .compile(&graph)
        .unwrap_or_else(|error| unreachable!("valid graph rejected: {error}"));
    let requested = rect(1, 1, 2, 2);
    let budget = ExecutionBudget::new(NonZeroUsize::MIN, 0, 64, CancellationToken::new());
    let result = engine
        .evaluate(&compiled, &name("result"), requested, QualityTier::Exact, &budget)
        .unwrap_or_else(|error| unreachable!("valid evaluation rejected: {error}"));

    assert_eq!(
        result.product.view().map(ProductView::bytes),
        Ok([20, 21, 22, 23, 24, 25, 26, 27, 36, 37, 38, 39, 40, 41, 42, 43].as_slice())
    );
    assert_eq!(result.trace.nodes.len(), 2);
    assert_eq!(result.report.counters.evaluated_nodes, 2);
    assert_eq!(result.report.counters.produced_samples, 8);
    let damage = engine
        .propagate_damage(&compiled, node_id(1), requested)
        .unwrap_or_else(|error| unreachable!("valid damage rejected: {error}"));
    assert_eq!(damage.get(&node_id(2)), Some(&requested));
}

fn graph(source_revision: ferrastra_core::ContentId) -> GraphDefinition {
    let source_node = node_id(1);
    let identity_node = node_id(2);
    let result_port = port("result");
    let mut builder = GraphBuilder::new(
        GraphSchemaVersion::new(1)
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}")),
        GraphRevisionId::new(1)
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}")),
    );
    builder
        .add_node(source_node, operation("ferrastra.source.raster"))
        .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"));
    builder
        .set_source_revision(source_node, source_revision)
        .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"));
    builder
        .add_node(identity_node, operation("ferrastra.core.identity"))
        .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"));
    builder
        .connect(
            NodeOutput { node: source_node, port: result_port.clone() },
            identity_node,
            port("source"),
        )
        .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"));
    builder
        .add_output(name("result"), NodeOutput { node: identity_node, port: result_port })
        .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"));
    builder.build()
}

fn operation(semantic_id: &str) -> OperationIdentity {
    OperationIdentity::new(
        SemanticOperationId::new(semantic_id)
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}")),
        SemanticVersion::new(1)
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}")),
    )
}

fn node_id(value: u64) -> NodeId {
    NodeId::new(value).unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"))
}

fn port(value: &str) -> PortId {
    PortId::new(value).unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"))
}

fn name(value: &str) -> GraphName {
    GraphName::new(value).unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"))
}

fn rect(x: i64, y: i64, width: u64, height: u64) -> IntRect {
    IntRect::new(x, y, width, height)
        .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"))
}
