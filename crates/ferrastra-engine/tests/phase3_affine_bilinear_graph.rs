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

//! Independent numerical and tile-equivalence proof for affine bilinear graphs.

use std::num::NonZeroUsize;

use ferrastra_core::{
    CancellationToken, ExecutionBudget, FiniteScalar, IntRect, IntSize, OperationIdentity,
    ParameterId, ParameterValue, PortId, ProductFormat, ProductView, QualityTier, RasterFormat,
    SemanticOperationId, SemanticVersion,
};
use ferrastra_engine::{CompiledPlan, Engine};
use ferrastra_graph::{
    GraphBuilder, GraphName, GraphRevisionId, GraphSchemaVersion, NodeId, NodeOutput,
};

const SOURCE_SIZE: (usize, usize) = (5, 4);
const DESTINATION_SIZE: (usize, usize) = (7, 6);
const MATRIX: [f64; 6] = [0.72, 0.18, -0.11, 0.83, 0.35, -0.2];

#[test]
fn affine_bilinear_matches_independent_encoded_oracle() {
    let source = source_pixels();
    let (engine, compiled) = graph(&source);
    let actual = evaluate(&engine, &compiled, rect(0, 0, 7, 6));
    let expected = oracle(&source);

    assert_eq!(actual, expected);
}

#[test]
fn affine_bilinear_tiles_equal_the_monolithic_product() {
    let source = source_pixels();
    let (engine, compiled) = graph(&source);
    let complete = evaluate(&engine, &compiled, rect(0, 0, 7, 6));
    let mut tiled = vec![0_u8; complete.len()];
    for region in [rect(0, 0, 3, 2), rect(3, 0, 4, 2), rect(0, 2, 3, 4), rect(3, 2, 4, 4)] {
        place_tile(&mut tiled, region, &evaluate(&engine, &compiled, region));
    }

    assert_eq!(tiled, complete);
}

#[allow(
    clippy::cast_possible_wrap,
    reason = "fixed fixture dimensions are small positive constants"
)]
fn graph(source: &[u8]) -> (Engine, CompiledPlan) {
    let mut engine =
        Engine::new().unwrap_or_else(|error| unreachable!("valid engine rejected: {error}"));
    let revision = engine
        .add_raster(
            ProductView::new(
                source,
                IntSize { width: SOURCE_SIZE.0 as u64, height: SOURCE_SIZE.1 as u64 },
                SOURCE_SIZE.0 * 4,
                ProductFormat::Raster(RasterFormat::Rgba8PremultipliedEncoded),
            )
            .unwrap_or_else(|error| unreachable!("valid source view rejected: {error}")),
        )
        .unwrap_or_else(|error| unreachable!("valid source rejected: {error}"));
    let source_node = node(1);
    let transform_node = node(2);
    let mut graph = GraphBuilder::new(schema(1), revision_id(1));
    graph
        .add_node(source_node, operation("ferrastra.source.raster"))
        .unwrap_or_else(|error| unreachable!("valid source node rejected: {error}"));
    graph
        .set_source_revision(source_node, revision)
        .unwrap_or_else(|error| unreachable!("valid revision rejected: {error}"));
    graph
        .add_node(transform_node, operation("ferrastra.resample.affine-bilinear"))
        .unwrap_or_else(|error| unreachable!("valid transform node rejected: {error}"));
    graph
        .connect(
            NodeOutput { node: source_node, port: port("result") },
            transform_node,
            port("source"),
        )
        .unwrap_or_else(|error| unreachable!("valid connection rejected: {error}"));
    for (name, value) in [
        ("source_width", SOURCE_SIZE.0 as i64),
        ("source_height", SOURCE_SIZE.1 as i64),
        ("destination_width", DESTINATION_SIZE.0 as i64),
        ("destination_height", DESTINATION_SIZE.1 as i64),
    ] {
        graph
            .set_parameter(transform_node, parameter(name), ParameterValue::Integer(value))
            .unwrap_or_else(|error| unreachable!("valid dimension rejected: {error}"));
    }
    for (name, value) in [
        ("source_m11", MATRIX[0]),
        ("source_m12", MATRIX[1]),
        ("source_m21", MATRIX[2]),
        ("source_m22", MATRIX[3]),
        ("source_tx", MATRIX[4]),
        ("source_ty", MATRIX[5]),
    ] {
        graph
            .set_parameter(
                transform_node,
                parameter(name),
                ParameterValue::Scalar(
                    FiniteScalar::new(value)
                        .unwrap_or_else(|error| unreachable!("valid scalar rejected: {error}")),
                ),
            )
            .unwrap_or_else(|error| unreachable!("valid matrix rejected: {error}"));
    }
    graph
        .set_parameter(
            transform_node,
            parameter("working_space"),
            ParameterValue::Enum(parameter("srgb_encoded")),
        )
        .unwrap_or_else(|error| unreachable!("valid space rejected: {error}"));
    graph
        .add_output(name("result"), NodeOutput { node: transform_node, port: port("result") })
        .unwrap_or_else(|error| unreachable!("valid output rejected: {error}"));
    let compiled = engine
        .compile(&graph.build())
        .unwrap_or_else(|error| unreachable!("valid graph rejected: {error}"));
    (engine, compiled)
}

fn evaluate(engine: &Engine, compiled: &CompiledPlan, region: IntRect) -> Vec<u8> {
    let requirements = engine
        .evaluation_requirements(compiled, &name("result"), region, QualityTier::Exact)
        .unwrap_or_else(|error| unreachable!("valid requirements rejected: {error}"));
    let result = engine
        .evaluate(
            compiled,
            &name("result"),
            region,
            QualityTier::Exact,
            &ExecutionBudget::new(
                NonZeroUsize::MIN,
                requirements.scratch_bytes,
                requirements.memory_bytes,
                CancellationToken::new(),
            ),
        )
        .unwrap_or_else(|error| unreachable!("valid evaluation rejected: {error}"));
    result.product.view().map_or_else(
        |error| unreachable!("valid result rejected: {error}"),
        |view| view.bytes().to_vec(),
    )
}

#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_precision_loss,
    clippy::cast_sign_loss,
    reason = "the independent oracle operates only on small fixed fixture coordinates and clamped bytes"
)]
fn oracle(source: &[u8]) -> Vec<u8> {
    let mut result = Vec::with_capacity(DESTINATION_SIZE.0 * DESTINATION_SIZE.1 * 4);
    for y in 0..DESTINATION_SIZE.1 {
        for x in 0..DESTINATION_SIZE.0 {
            let source_x = MATRIX[0].mul_add(x as f64, MATRIX[2].mul_add(y as f64, MATRIX[4]));
            let source_y = MATRIX[1].mul_add(x as f64, MATRIX[3].mul_add(y as f64, MATRIX[5]));
            let left = source_x.floor() as i64;
            let top = source_y.floor() as i64;
            let fx = source_x - left as f64;
            let fy = source_y - top as f64;
            let mut sample = [0.0; 4];
            for (tap_x, tap_y, weight) in [
                (left, top, (1.0 - fx) * (1.0 - fy)),
                (left + 1, top, fx * (1.0 - fy)),
                (left, top + 1, (1.0 - fx) * fy),
                (left + 1, top + 1, fx * fy),
            ] {
                if let Some(tap) = source_sample(source, tap_x, tap_y) {
                    for channel in 0..4 {
                        sample[channel] += f64::from(tap[channel]) * weight;
                    }
                }
            }
            result.extend(sample.map(|value| value.round().clamp(0.0, 255.0) as u8));
        }
    }
    result
}

fn source_sample(source: &[u8], x: i64, y: i64) -> Option<[u8; 4]> {
    let x = usize::try_from(x).ok()?;
    let y = usize::try_from(y).ok()?;
    if x >= SOURCE_SIZE.0 || y >= SOURCE_SIZE.1 {
        return None;
    }
    let offset = (y * SOURCE_SIZE.0 + x) * 4;
    <[u8; 4]>::try_from(source.get(offset..offset + 4)?).ok()
}

#[allow(
    clippy::cast_possible_truncation,
    reason = "the fixed fixture arithmetic is bounded within the complete u8 domain"
)]
fn source_pixels() -> Vec<u8> {
    (0..SOURCE_SIZE.0 * SOURCE_SIZE.1)
        .flat_map(|index| {
            let alpha = 96 + (index * 7 % 160) as u8;
            [alpha / 4, alpha / 2, ((u16::from(alpha) * 3) / 4) as u8, alpha]
        })
        .collect()
}

fn place_tile(destination: &mut [u8], region: IntRect, tile: &[u8]) {
    let width = usize::try_from(region.size().width)
        .unwrap_or_else(|error| unreachable!("valid width rejected: {error}"));
    let height = usize::try_from(region.size().height)
        .unwrap_or_else(|error| unreachable!("valid height rejected: {error}"));
    let x = usize::try_from(region.origin().x)
        .unwrap_or_else(|error| unreachable!("valid x rejected: {error}"));
    let y = usize::try_from(region.origin().y)
        .unwrap_or_else(|error| unreachable!("valid y rejected: {error}"));
    for row in 0..height {
        let source_start = row * width * 4;
        let destination_start = ((y + row) * DESTINATION_SIZE.0 + x) * 4;
        destination[destination_start..destination_start + width * 4]
            .copy_from_slice(&tile[source_start..source_start + width * 4]);
    }
}

fn operation(value: &str) -> OperationIdentity {
    OperationIdentity::new(
        SemanticOperationId::new(value)
            .unwrap_or_else(|error| unreachable!("valid operation rejected: {error}")),
        SemanticVersion::new(1)
            .unwrap_or_else(|error| unreachable!("valid version rejected: {error}")),
    )
}

fn node(value: u64) -> NodeId {
    NodeId::new(value).unwrap_or_else(|error| unreachable!("valid node rejected: {error}"))
}

fn schema(value: u32) -> GraphSchemaVersion {
    GraphSchemaVersion::new(value)
        .unwrap_or_else(|error| unreachable!("valid schema rejected: {error}"))
}

fn revision_id(value: u64) -> GraphRevisionId {
    GraphRevisionId::new(value)
        .unwrap_or_else(|error| unreachable!("valid revision rejected: {error}"))
}

fn parameter(value: &str) -> ParameterId {
    ParameterId::new(value)
        .unwrap_or_else(|error| unreachable!("valid parameter rejected: {error}"))
}

fn port(value: &str) -> PortId {
    PortId::new(value).unwrap_or_else(|error| unreachable!("valid port rejected: {error}"))
}

fn name(value: &str) -> GraphName {
    GraphName::new(value).unwrap_or_else(|error| unreachable!("valid name rejected: {error}"))
}

fn rect(x: i64, y: i64, width: u64, height: u64) -> IntRect {
    IntRect::new(x, y, width, height)
        .unwrap_or_else(|error| unreachable!("valid region rejected: {error}"))
}
