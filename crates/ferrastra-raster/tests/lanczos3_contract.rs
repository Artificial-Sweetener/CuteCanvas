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

//! Contract proof for canonical Lanczos3 geometry, pixels, tiles, edges, and budgets.

#[path = "support/lanczos3_fixture.rs"]
#[allow(dead_code, reason = "the sampled-view contract uses the other shared fixtures")]
mod fixture;
#[path = "support/lanczos3_oracle.rs"]
#[allow(dead_code, reason = "the sampled-view contract uses the other shared oracle entry")]
mod oracle;

use std::num::NonZeroUsize;

use ferrastra_core::{
    CancellationToken, ExecutionBudget, InputDemand, IntSize, MemoryEstimateError, Operation,
    OperationExecutionError, OperationInput, OperationKernel, OperationOutput, OperationParameters,
    ParameterValue,
};

use fixture::{
    ResizeCase, execute_region, full_region, operation, patterned_source, rect, request,
};
use oracle::OracleEdge;

#[test]
fn descriptor_and_required_region_publish_the_complete_spatial_contract() {
    let operation = operation();
    let request = request(rect(50, 40, 10, 8), (100, 80), (200, 160), "clamp", "srgb_linear");

    assert!(operation.descriptor().validate().is_ok());
    assert_eq!(
        operation.backward_demand(&request),
        Ok(vec![InputDemand { port: fixture::port("source"), region: rect(22, 17, 11, 10) }]
            .into_boxed_slice())
    );
    assert_eq!(operation.memory(&request).map(|memory| memory.destination_bytes), Ok(320));
}

#[test]
fn scalar_result_matches_an_independent_two_dimensional_oracle() {
    let source_size = (7, 5);
    let destination_size = (4, 9);
    let source = patterned_source(source_size);
    for (edge_name, oracle_edge) in [
        ("clamp", OracleEdge::Clamp),
        ("transparent", OracleEdge::Transparent),
        ("reflect", OracleEdge::Reflect),
        ("wrap", OracleEdge::Wrap),
    ] {
        for (space_name, linear) in [("srgb_encoded", false), ("srgb_linear", true)] {
            let actual = execute_region(
                &source,
                ResizeCase {
                    source_size,
                    destination_size,
                    region: full_region(destination_size),
                    edge: edge_name,
                    space: space_name,
                    source_padding: 5,
                    destination_padding: 7,
                },
            );
            let expected =
                oracle::resize(&source, source_size, destination_size, oracle_edge, linear);
            fixture::assert_pixels_within(&actual, &expected, 1);
        }
    }
}

#[test]
fn tiled_and_monolithic_results_are_byte_identical() {
    let source_size = (9, 7);
    let destination_size = (13, 11);
    let source = patterned_source(source_size);
    let complete = execute_region(
        &source,
        ResizeCase {
            source_size,
            destination_size,
            region: full_region(destination_size),
            edge: "reflect",
            space: "srgb_linear",
            source_padding: 3,
            destination_padding: 5,
        },
    );
    let mut tiled = vec![0_u8; destination_size.0 * destination_size.1 * 4];
    for region in [rect(0, 0, 6, 5), rect(6, 0, 7, 5), rect(0, 5, 6, 6), rect(6, 5, 7, 6)] {
        let tile = execute_region(
            &source,
            ResizeCase {
                source_size,
                destination_size,
                region,
                edge: "reflect",
                space: "srgb_linear",
                source_padding: 2,
                destination_padding: 3,
            },
        );
        fixture::place_tile(&mut tiled, destination_size.0, region, &tile);
    }
    assert_eq!(tiled, complete);
}

#[test]
fn identity_mapping_preserves_pixels_and_ignores_hidden_transparent_color() {
    let source_size = (3, 2);
    let source = vec![
        10, 20, 30, 255, 80, 70, 60, 128, 255, 200, 100, 0, 3, 2, 1, 255, 0, 0, 0, 0, 40, 50, 60,
        64,
    ];
    let expected = vec![
        10, 20, 30, 255, 80, 70, 60, 128, 0, 0, 0, 0, 3, 2, 1, 255, 0, 0, 0, 0, 40, 50, 60, 64,
    ];
    for space in ["srgb_encoded", "srgb_linear"] {
        assert_eq!(
            execute_region(
                &source,
                ResizeCase {
                    source_size,
                    destination_size: source_size,
                    region: full_region(source_size),
                    edge: "clamp",
                    space,
                    source_padding: 4,
                    destination_padding: 6,
                },
            ),
            expected
        );
    }
}

#[test]
fn one_pixel_sources_obey_each_edge_mode_and_empty_requests_are_noops() {
    let source = [24, 12, 6, 32];
    for edge in ["clamp", "transparent", "reflect", "wrap"] {
        assert_eq!(
            execute_region(
                &source,
                ResizeCase {
                    source_size: (1, 1),
                    destination_size: (1, 1),
                    region: rect(0, 0, 1, 1),
                    edge,
                    space: "srgb_encoded",
                    source_padding: 9,
                    destination_padding: 11,
                },
            ),
            source
        );
    }
    assert!(
        execute_region(
            &source,
            ResizeCase {
                source_size: (1, 1),
                destination_size: (4, 4),
                region: rect(2, 1, 0, 0),
                edge: "transparent",
                space: "srgb_linear",
                source_padding: 0,
                destination_padding: 0,
            },
        )
        .is_empty()
    );
}

#[test]
fn cancellation_and_scratch_limits_reject_before_publication() {
    let operation = operation();
    let source_size = (4, 4);
    let destination_size = (7, 7);
    let request = request(
        full_region(destination_size),
        source_size,
        destination_size,
        "clamp",
        "srgb_linear",
    );
    let source = patterned_source(source_size);
    let source_port = fixture::port("source");
    let result_port = fixture::port("result");
    let input = OperationInput {
        port: &source_port,
        region: rect(0, 0, 4, 4),
        product: fixture::view(&source, IntSize { width: 4, height: 4 }, 16),
    };
    let mut destination = vec![0xaa; destination_size.0 * destination_size.1 * 4];
    let cancellation = CancellationToken::new();
    cancellation.cancel();
    let result = {
        let output = OperationOutput {
            port: &result_port,
            region: request.output_region,
            product: fixture::mutable_view(
                &mut destination,
                fixture::int_size(destination_size),
                destination_size.0 * 4,
            ),
        };
        operation.execute(
            &request,
            &[input],
            &mut [output],
            &ExecutionBudget::new(NonZeroUsize::MIN, u64::MAX, u64::MAX, cancellation),
        )
    };
    assert_eq!(result, Err(OperationExecutionError::Cancelled));
    assert!(destination.iter().all(|value| *value == 0xaa));

    let memory = operation
        .memory(&request)
        .unwrap_or_else(|error| unreachable!("valid memory request rejected: {error}"));
    assert!(memory.scratch_bytes > 0);
    let mut rejected_destination = vec![0_u8; destination_size.0 * destination_size.1 * 4];
    let rejected = OperationOutput {
        port: &result_port,
        region: request.output_region,
        product: fixture::mutable_view(
            &mut rejected_destination,
            fixture::int_size(destination_size),
            destination_size.0 * 4,
        ),
    };
    assert_eq!(
        operation.execute(
            &request,
            &[input],
            &mut [rejected],
            &ExecutionBudget::new(
                NonZeroUsize::MIN,
                memory.scratch_bytes - 1,
                u64::MAX,
                CancellationToken::new(),
            ),
        ),
        Err(OperationExecutionError::BudgetExceeded)
    );
}

#[test]
fn invalid_dimensions_fail_planning_and_memory_admission() {
    let mut request = request(rect(0, 0, 1, 1), (1, 1), (1, 1), "clamp", "srgb_linear");
    let mut values = fixture::parameter_values((1, 1), (1, 1), "clamp", "srgb_linear");
    values.insert(fixture::parameter("destination_width"), ParameterValue::Integer(0));
    request.parameters = OperationParameters::new(values);

    assert!(operation().backward_demand(&request).is_err());
    assert_eq!(operation().memory(&request), Err(MemoryEstimateError::InvalidParameters));
}
