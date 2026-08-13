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

//! Focused construction and regional-execution fixtures for Lanczos3 contract tests.

use std::collections::BTreeMap;
use std::num::NonZeroUsize;

use ferrastra_core::{
    CancellationToken, ExecutionBudget, IntRect, IntSize, Operation, OperationInput,
    OperationKernel, OperationOutput, OperationParameters, OperationRequest, ParameterId,
    ParameterValue, PortId, ProductFormat, ProductSpec, ProductView, ProductViewMut, QualityTier,
    RasterFormat,
};
use ferrastra_raster::{Lanczos3Operation, Lanczos3ViewOperation};

#[derive(Clone, Copy)]
pub(crate) struct ResizeCase<'a> {
    pub(crate) source_size: (usize, usize),
    pub(crate) destination_size: (usize, usize),
    pub(crate) region: IntRect,
    pub(crate) edge: &'a str,
    pub(crate) space: &'a str,
    pub(crate) source_padding: usize,
    pub(crate) destination_padding: usize,
}

#[derive(Clone, Copy)]
pub(crate) struct ViewCase<'a> {
    pub(crate) source_size: (usize, usize),
    pub(crate) destination_size: (usize, usize),
    pub(crate) first_center: (f64, f64),
    pub(crate) source_step: (f64, f64),
    pub(crate) region: IntRect,
    pub(crate) edge: &'a str,
    pub(crate) space: &'a str,
}

pub(crate) fn execute_region(source: &[u8], case: ResizeCase<'_>) -> Vec<u8> {
    let operation = operation();
    let request =
        request(case.region, case.source_size, case.destination_size, case.edge, case.space);
    let demand = operation
        .backward_demand(&request)
        .unwrap_or_else(|error| unreachable!("valid demand rejected: {error}"))[0]
        .region;
    let (regional_source, source_stride) =
        crop_source(source, case.source_size.0, demand, case.source_padding);
    let output_width = usize::try_from(case.region.size().width)
        .unwrap_or_else(|_| unreachable!("fixture width fits usize"));
    let output_height = usize::try_from(case.region.size().height)
        .unwrap_or_else(|_| unreachable!("fixture height fits usize"));
    let output_stride = output_width * 4 + case.destination_padding;
    let mut padded_output = if output_width == 0 || output_height == 0 {
        Vec::new()
    } else {
        vec![0xcc; (output_height - 1) * output_stride + output_width * 4]
    };
    let source_port = port("source");
    let result_port = port("result");
    let input = OperationInput {
        port: &source_port,
        region: demand,
        product: view(&regional_source, demand.size(), source_stride),
    };
    let memory = operation
        .memory(&request)
        .unwrap_or_else(|error| unreachable!("valid memory request rejected: {error}"));
    {
        let output = OperationOutput {
            port: &result_port,
            region: case.region,
            product: mutable_view(&mut padded_output, case.region.size(), output_stride),
        };
        operation
            .execute(
                &request,
                &[input],
                &mut [output],
                &ExecutionBudget::new(
                    NonZeroUsize::MIN,
                    memory.scratch_bytes,
                    memory
                        .checked_peak_bytes()
                        .unwrap_or_else(|error| unreachable!("fixture memory fits: {error}")),
                    CancellationToken::new(),
                ),
            )
            .unwrap_or_else(|error| unreachable!("valid resize rejected: {error}"));
    }
    tighten(&padded_output, output_width, output_height, output_stride)
}

pub(crate) fn execute_view_region(source: &[u8], case: ViewCase<'_>) -> Vec<u8> {
    let operation = Lanczos3ViewOperation::new()
        .unwrap_or_else(|error| unreachable!("valid operation rejected: {error}"));
    let mut values =
        parameter_values(case.source_size, case.destination_size, case.edge, case.space);
    for (name, value) in [
        ("source_center_x", case.first_center.0),
        ("source_center_y", case.first_center.1),
        ("source_step_x", case.source_step.0),
        ("source_step_y", case.source_step.1),
    ] {
        values.insert(parameter(name), scalar(value));
    }
    let request = OperationRequest {
        output_region: case.region,
        output: ProductSpec::raster(RasterFormat::Rgba8PremultipliedEncoded),
        quality: QualityTier::Exact,
        parameters: OperationParameters::new(values),
    };
    let demand = operation
        .backward_demand(&request)
        .unwrap_or_else(|error| unreachable!("valid demand rejected: {error}"))[0]
        .region;
    let (regional_source, source_stride) = crop_source(source, case.source_size.0, demand, 3);
    let width = usize::try_from(case.region.size().width).unwrap_or(0);
    let height = usize::try_from(case.region.size().height).unwrap_or(0);
    let output_stride = width * 4 + 5;
    let mut output = if width == 0 || height == 0 {
        Vec::new()
    } else {
        vec![0xcc; (height - 1) * output_stride + width * 4]
    };
    let source_port = port("source");
    let result_port = port("result");
    let input = OperationInput {
        port: &source_port,
        region: demand,
        product: view(&regional_source, demand.size(), source_stride),
    };
    let memory = operation
        .memory(&request)
        .unwrap_or_else(|error| unreachable!("valid memory rejected: {error}"));
    let output_view = OperationOutput {
        port: &result_port,
        region: case.region,
        product: mutable_view(&mut output, case.region.size(), output_stride),
    };
    operation
        .execute(
            &request,
            &[input],
            &mut [output_view],
            &ExecutionBudget::new(
                NonZeroUsize::MIN,
                memory.scratch_bytes,
                memory
                    .checked_peak_bytes()
                    .unwrap_or_else(|error| unreachable!("fixture memory fits: {error}")),
                CancellationToken::new(),
            ),
        )
        .unwrap_or_else(|error| unreachable!("valid sampled view rejected: {error}"));
    tighten(&output, width, height, output_stride)
}

pub(crate) fn request(
    output_region: IntRect,
    source_size: (usize, usize),
    destination_size: (usize, usize),
    edge: &str,
    space: &str,
) -> OperationRequest {
    OperationRequest {
        output_region,
        output: ProductSpec::raster(RasterFormat::Rgba8PremultipliedEncoded),
        quality: QualityTier::Exact,
        parameters: OperationParameters::new(parameter_values(
            source_size,
            destination_size,
            edge,
            space,
        )),
    }
}

pub(crate) fn parameter_values(
    source_size: (usize, usize),
    destination_size: (usize, usize),
    edge: &str,
    space: &str,
) -> BTreeMap<ParameterId, ParameterValue> {
    BTreeMap::from([
        (parameter("source_width"), integer(source_size.0)),
        (parameter("source_height"), integer(source_size.1)),
        (parameter("destination_width"), integer(destination_size.0)),
        (parameter("destination_height"), integer(destination_size.1)),
        (parameter("edge_mode"), enumeration(edge)),
        (parameter("working_space"), enumeration(space)),
    ])
}

pub(crate) fn patterned_source(size: (usize, usize)) -> Vec<u8> {
    let mut state = 0x6d2b_79f5_u32;
    let mut result = Vec::with_capacity(size.0 * size.1 * 4);
    for _ in 0..size.0 * size.1 {
        state = state.wrapping_mul(1_664_525).wrapping_add(1_013_904_223);
        let alpha = state.to_le_bytes()[0];
        for shift in [8, 16, 24] {
            let channel = ((state >> shift) & 0xff).to_le_bytes()[0].min(alpha);
            result.push(channel);
        }
        result.push(alpha);
    }
    result
}

pub(crate) fn place_tile(
    destination: &mut [u8],
    destination_width: usize,
    region: IntRect,
    tile: &[u8],
) {
    let width = usize::try_from(region.size().width).unwrap_or(0);
    let height = usize::try_from(region.size().height).unwrap_or(0);
    let origin_x = usize::try_from(region.origin().x).unwrap_or(0);
    let origin_y = usize::try_from(region.origin().y).unwrap_or(0);
    for row in 0..height {
        let destination_start = ((origin_y + row) * destination_width + origin_x) * 4;
        let source_start = row * width * 4;
        destination[destination_start..destination_start + width * 4]
            .copy_from_slice(&tile[source_start..source_start + width * 4]);
    }
}

pub(crate) fn assert_pixels_within(actual: &[u8], expected: &[u8], tolerance: u8) {
    assert_eq!(actual.len(), expected.len());
    for (index, (&actual, &expected)) in actual.iter().zip(expected).enumerate() {
        assert!(
            actual.abs_diff(expected) <= tolerance,
            "byte {index}: actual {actual}, expected {expected}, tolerance {tolerance}"
        );
    }
}

pub(crate) fn operation() -> Lanczos3Operation {
    Lanczos3Operation::new()
        .unwrap_or_else(|error| unreachable!("valid operation rejected: {error}"))
}

pub(crate) fn view(bytes: &[u8], size: IntSize, stride: usize) -> ProductView<'_> {
    ProductView::new(bytes, size, stride, format())
        .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"))
}

pub(crate) fn mutable_view(bytes: &mut [u8], size: IntSize, stride: usize) -> ProductViewMut<'_> {
    ProductViewMut::new(bytes, size, stride, format())
        .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"))
}

pub(crate) fn full_region(size: (usize, usize)) -> IntRect {
    rect(0, 0, usize_as_u64(size.0), usize_as_u64(size.1))
}

pub(crate) fn int_size(size: (usize, usize)) -> IntSize {
    IntSize { width: usize_as_u64(size.0), height: usize_as_u64(size.1) }
}

pub(crate) fn rect(x: i64, y: i64, width: u64, height: u64) -> IntRect {
    IntRect::new(x, y, width, height)
        .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"))
}

pub(crate) fn port(value: &str) -> PortId {
    PortId::new(value).unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"))
}

pub(crate) fn parameter(value: &str) -> ParameterId {
    ParameterId::new(value).unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"))
}

fn crop_source(
    source: &[u8],
    source_width: usize,
    region: IntRect,
    padding: usize,
) -> (Vec<u8>, usize) {
    let width = usize::try_from(region.size().width).unwrap_or(0);
    let height = usize::try_from(region.size().height).unwrap_or(0);
    let stride = width * 4 + padding;
    if width == 0 || height == 0 {
        return (Vec::new(), stride);
    }
    let mut result = vec![0xdd; (height - 1) * stride + width * 4];
    let origin_x = usize::try_from(region.origin().x).unwrap_or(0);
    let origin_y = usize::try_from(region.origin().y).unwrap_or(0);
    for row in 0..height {
        let source_start = ((origin_y + row) * source_width + origin_x) * 4;
        let destination_start = row * stride;
        result[destination_start..destination_start + width * 4]
            .copy_from_slice(&source[source_start..source_start + width * 4]);
    }
    (result, stride)
}

fn tighten(source: &[u8], width: usize, height: usize, stride: usize) -> Vec<u8> {
    let mut result = Vec::with_capacity(width * height * 4);
    for row in 0..height {
        result.extend_from_slice(&source[row * stride..row * stride + width * 4]);
    }
    result
}

fn format() -> ProductFormat {
    ProductFormat::Raster(RasterFormat::Rgba8PremultipliedEncoded)
}

fn integer(value: usize) -> ParameterValue {
    ParameterValue::Integer(
        i64::try_from(value).unwrap_or_else(|_| unreachable!("fixture dimension fits i64")),
    )
}

fn enumeration(value: &str) -> ParameterValue {
    ParameterValue::Enum(parameter(value))
}

fn scalar(value: f64) -> ParameterValue {
    ParameterValue::Scalar(
        ferrastra_core::FiniteScalar::new(value)
            .unwrap_or_else(|error| unreachable!("fixture scalar rejected: {error}")),
    )
}

fn usize_as_u64(value: usize) -> u64 {
    u64::try_from(value).unwrap_or_else(|_| unreachable!("fixture dimension fits u64"))
}
