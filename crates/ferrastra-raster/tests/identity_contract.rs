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

//! Contract proof for exact regional identity, strides, demand, damage, and cancellation.

use std::num::NonZeroUsize;

use ferrastra_core::{
    CancellationToken, ExecutionBudget, IntRect, IntSize, Operation, OperationDamageRequest,
    OperationExecutionError, OperationInput, OperationKernel, OperationOutput, OperationParameters,
    OperationRequest, PortId, ProductFormat, ProductSpec, ProductView, ProductViewMut, QualityTier,
    RasterFormat,
};
use ferrastra_raster::{IdentityOperation, RasterSourceOperation};

#[test]
fn identity_copies_exact_samples_across_different_valid_strides() {
    let operation = IdentityOperation::new()
        .unwrap_or_else(|error| unreachable!("valid operation rejected: {error}"));
    let source_port = port("source");
    let result_port = port("result");
    let region = rect(7, -3, 2, 2);
    let source_bytes = [1, 2, 3, 4, 5, 6, 7, 8, 99, 99, 99, 99, 9, 10, 11, 12, 13, 14, 15, 16];
    let mut destination_bytes = [0xaa; 32];
    let input = OperationInput { port: &source_port, region, product: view(&source_bytes, 12) };
    let request = request(region);
    let budget = budget(CancellationToken::new());
    {
        let output = OperationOutput {
            port: &result_port,
            region,
            product: mutable_view(&mut destination_bytes, 16),
        };
        operation
            .execute(&request, &[input], &mut [output], &budget)
            .unwrap_or_else(|error| unreachable!("valid execution rejected: {error}"));
    }

    assert_eq!(&destination_bytes[0..8], &source_bytes[0..8]);
    assert_eq!(&destination_bytes[16..24], &source_bytes[12..20]);
    assert!(destination_bytes[8..16].iter().all(|value| *value == 0xaa));
}

#[test]
fn cancellation_publishes_no_identity_result() {
    let operation = IdentityOperation::new()
        .unwrap_or_else(|error| unreachable!("valid operation rejected: {error}"));
    let source_port = port("source");
    let result_port = port("result");
    let region = rect(0, 0, 2, 2);
    let source_bytes = [1_u8; 16];
    let mut destination_bytes = [0xaa; 16];
    let cancellation = CancellationToken::new();
    cancellation.cancel();
    let result = {
        let input = OperationInput { port: &source_port, region, product: view(&source_bytes, 8) };
        let output = OperationOutput {
            port: &result_port,
            region,
            product: mutable_view(&mut destination_bytes, 8),
        };
        operation.execute(&request(region), &[input], &mut [output], &budget(cancellation))
    };

    assert_eq!(result, Err(OperationExecutionError::Cancelled));
    assert_eq!(destination_bytes, [0xaa; 16]);
}

#[test]
fn source_and_identity_publish_complete_spatial_contracts() {
    let source = RasterSourceOperation::new()
        .unwrap_or_else(|error| unreachable!("valid operation rejected: {error}"));
    let identity = IdentityOperation::new()
        .unwrap_or_else(|error| unreachable!("valid operation rejected: {error}"));
    let region = rect(-5, 9, 3, 4);
    let request = request(region);

    assert_eq!(source.backward_demand(&request), Ok(Box::default()));
    assert_eq!(
        identity.backward_demand(&request),
        Ok(vec![ferrastra_core::InputDemand { port: port("source"), region }].into_boxed_slice())
    );
    assert_eq!(
        identity.forward_damage(&OperationDamageRequest {
            input: port("source"),
            input_damage: region,
            parameters: OperationParameters::default(),
        }),
        Ok(region)
    );
    assert!(source.descriptor().validate().is_ok());
    assert!(identity.descriptor().validate().is_ok());
}

fn request(output_region: IntRect) -> OperationRequest {
    OperationRequest {
        output_region,
        output: ProductSpec::raster(RasterFormat::Rgba8PremultipliedEncoded),
        quality: QualityTier::Exact,
        parameters: OperationParameters::default(),
    }
}

fn view(bytes: &[u8], stride_bytes: usize) -> ProductView<'_> {
    ProductView::new(bytes, size(), stride_bytes, format())
        .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"))
}

fn mutable_view(bytes: &mut [u8], stride_bytes: usize) -> ProductViewMut<'_> {
    ProductViewMut::new(bytes, size(), stride_bytes, format())
        .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"))
}

fn size() -> IntSize {
    IntSize { width: 2, height: 2 }
}

fn format() -> ProductFormat {
    ProductFormat::Raster(RasterFormat::Rgba8PremultipliedEncoded)
}

fn rect(x: i64, y: i64, width: u64, height: u64) -> IntRect {
    IntRect::new(x, y, width, height)
        .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"))
}

fn port(value: &str) -> PortId {
    PortId::new(value).unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"))
}

fn budget(cancellation: CancellationToken) -> ExecutionBudget {
    ExecutionBudget::new(NonZeroUsize::MIN, 0, 64, cancellation)
}
