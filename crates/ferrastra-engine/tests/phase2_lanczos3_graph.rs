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

//! Public graph/runtime proof for exact Lanczos3 evaluation and spatial damage.

use std::num::NonZeroUsize;

use ferrastra_core::{
    CancellationToken, ExecutionBudget, IntRect, IntSize, OperationIdentity, ParameterId,
    ParameterValue, PortId, ProductFormat, ProductView, QualityTier, RasterFormat,
    SemanticOperationId, SemanticVersion,
};
use ferrastra_engine::Engine;
use ferrastra_graph::{
    GraphBuilder, GraphName, GraphRevisionId, GraphSchemaVersion, NodeId, NodeOutput,
};

#[test]
fn source_to_lanczos3_graph_resizes_exact_pixels_and_propagates_damage() {
    let mut engine =
        Engine::new().unwrap_or_else(|error| unreachable!("valid engine rejected: {error}"));
    let source_pixel = [12_u8, 24, 36, 255];
    let source_bytes = source_pixel.repeat(4);
    let revision = engine
        .add_raster(
            ProductView::new(
                &source_bytes,
                IntSize { width: 2, height: 2 },
                8,
                ProductFormat::Raster(RasterFormat::Rgba8PremultipliedEncoded),
            )
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}")),
        )
        .unwrap_or_else(|error| unreachable!("valid source rejected: {error}"));
    let source_node = node(1);
    let resize_node = node(2);
    let result_port = port("result");
    let mut graph = GraphBuilder::new(schema(1), revision_id(1));
    graph
        .add_node(source_node, operation("ferrastra.source.raster"))
        .unwrap_or_else(|error| unreachable!("valid source node rejected: {error}"));
    graph
        .set_source_revision(source_node, revision)
        .unwrap_or_else(|error| unreachable!("valid revision rejected: {error}"));
    graph
        .add_node(resize_node, operation("ferrastra.resample.lanczos3"))
        .unwrap_or_else(|error| unreachable!("valid resize node rejected: {error}"));
    graph
        .connect(
            NodeOutput { node: source_node, port: result_port.clone() },
            resize_node,
            port("source"),
        )
        .unwrap_or_else(|error| unreachable!("valid connection rejected: {error}"));
    for (name, value) in [
        ("source_width", 2),
        ("source_height", 2),
        ("destination_width", 5),
        ("destination_height", 3),
    ] {
        graph
            .set_parameter(resize_node, parameter(name), ParameterValue::Integer(value))
            .unwrap_or_else(|error| unreachable!("valid parameter rejected: {error}"));
    }
    graph
        .add_output(name("result"), NodeOutput { node: resize_node, port: result_port })
        .unwrap_or_else(|error| unreachable!("valid output rejected: {error}"));
    let compiled = engine
        .compile(&graph.build())
        .unwrap_or_else(|error| unreachable!("valid graph rejected: {error}"));
    let output_region = rect(0, 0, 5, 3);
    let requirements = engine
        .evaluation_requirements(&compiled, &name("result"), output_region, QualityTier::Exact)
        .unwrap_or_else(|error| unreachable!("valid requirements rejected: {error}"));
    assert!(requirements.memory_bytes > requirements.scratch_bytes);
    assert!(requirements.scratch_bytes > 0);
    let insufficient_scratch = ExecutionBudget::new(
        NonZeroUsize::MIN,
        requirements.scratch_bytes - 1,
        requirements.memory_bytes,
        CancellationToken::new(),
    );
    assert!(
        engine
            .evaluate(
                &compiled,
                &name("result"),
                output_region,
                QualityTier::Exact,
                &insufficient_scratch,
            )
            .is_err()
    );
    let result = engine
        .evaluate(
            &compiled,
            &name("result"),
            output_region,
            QualityTier::Exact,
            &ExecutionBudget::new(
                NonZeroUsize::MIN,
                requirements.scratch_bytes,
                requirements.memory_bytes,
                CancellationToken::new(),
            ),
        )
        .unwrap_or_else(|error| unreachable!("valid evaluation rejected: {error}"));

    assert_eq!(
        result.product.view().map(ProductView::bytes),
        Ok(source_pixel.repeat(15).as_slice())
    );
    assert_eq!(result.trace.nodes.len(), 2);
    assert_eq!(result.report.counters.evaluated_nodes, 2);
    assert_eq!(result.report.peak_memory_bytes, requirements.memory_bytes);
    let damage = engine
        .propagate_damage(&compiled, source_node, rect(0, 0, 1, 2))
        .unwrap_or_else(|error| unreachable!("valid damage rejected: {error}"));
    assert_eq!(damage.get(&resize_node), Some(&output_region));
}

fn operation(value: &str) -> OperationIdentity {
    OperationIdentity::new(
        SemanticOperationId::new(value)
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}")),
        SemanticVersion::new(1)
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}")),
    )
}

fn node(value: u64) -> NodeId {
    NodeId::new(value).unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"))
}

fn schema(value: u32) -> GraphSchemaVersion {
    GraphSchemaVersion::new(value)
        .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"))
}

fn revision_id(value: u64) -> GraphRevisionId {
    GraphRevisionId::new(value)
        .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"))
}

fn parameter(value: &str) -> ParameterId {
    ParameterId::new(value).unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"))
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
