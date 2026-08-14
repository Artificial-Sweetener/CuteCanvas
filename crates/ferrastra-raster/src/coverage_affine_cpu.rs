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

//! Responsibility: Execute canonical range-preserving affine Coverage8 sampling on the CPU.
//!
//! Does not own: operation descriptors, source storage, graph policy, or presentation.

use ferrastra_core::{
    CoverageFormat, ExecutionBudget, OperationExecutionError, OperationInput, OperationOutput,
    OperationRequest, ProductFormat,
};

use crate::affine_contract::AffineGeometryContract;
use crate::coverage_area_cpu;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum CoverageFilter {
    Nearest,
    Linear,
    Area,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum CoverageEdge {
    Transparent,
    Clamp,
}

pub(crate) fn execute(
    request: &OperationRequest,
    input: &OperationInput<'_>,
    output: &mut OperationOutput<'_>,
    contract: AffineGeometryContract,
    filter: CoverageFilter,
    edge: CoverageEdge,
    budget: &ExecutionBudget,
) -> Result<(), OperationExecutionError> {
    validate(request, input, output, contract)?;
    let width = usize::try_from(request.output_region.size().width)
        .map_err(|_| OperationExecutionError::InvalidProduct)?;
    let height = usize::try_from(request.output_region.size().height)
        .map_err(|_| OperationExecutionError::InvalidProduct)?;
    if filter == CoverageFilter::Area
        && coverage_area_cpu::execute_if_aligned(request, input, output, contract, budget)?
    {
        return Ok(());
    }
    let stride = output.product.stride_bytes();
    let destination = output.product.bytes_mut();
    for local_y in 0..height {
        for local_x in 0..width {
            if budget.should_cancel_now() {
                return Err(OperationExecutionError::Cancelled);
            }
            let output_x = request.output_region.origin().x
                + i64::try_from(local_x).map_err(|_| OperationExecutionError::InvalidProduct)?;
            let output_y = request.output_region.origin().y
                + i64::try_from(local_y).map_err(|_| OperationExecutionError::InvalidProduct)?;
            let source = contract.source_coordinate(output_x, output_y);
            let sample = match filter {
                CoverageFilter::Nearest => nearest(input, source.x, source.y, contract, edge)?,
                CoverageFilter::Linear => bilinear(input, source.x, source.y, contract, edge)?,
                CoverageFilter::Area => area(input, source.x, source.y, contract, edge)?,
            };
            let offset = local_y
                .checked_mul(stride)
                .and_then(|row| row.checked_add(local_x))
                .ok_or(OperationExecutionError::InvalidProduct)?;
            destination[offset] = quantize(sample);
        }
    }
    Ok(())
}

#[allow(
    clippy::cast_possible_truncation,
    reason = "finite source coordinates are bounded by validated product dimensions"
)]
fn nearest(
    input: &OperationInput<'_>,
    x: f64,
    y: f64,
    contract: AffineGeometryContract,
    edge: CoverageEdge,
) -> Result<f64, OperationExecutionError> {
    read_sample(input, x.round() as i64, y.round() as i64, contract, edge)
}

#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_precision_loss,
    reason = "finite source coordinates are bounded by validated product dimensions"
)]
fn bilinear(
    input: &OperationInput<'_>,
    x: f64,
    y: f64,
    contract: AffineGeometryContract,
    edge: CoverageEdge,
) -> Result<f64, OperationExecutionError> {
    let left = x.floor() as i64;
    let top = y.floor() as i64;
    let fraction_x = x - left as f64;
    let fraction_y = y - top as f64;
    let taps = [
        (left, top, (1.0 - fraction_x) * (1.0 - fraction_y)),
        (left + 1, top, fraction_x * (1.0 - fraction_y)),
        (left, top + 1, (1.0 - fraction_x) * fraction_y),
        (left + 1, top + 1, fraction_x * fraction_y),
    ];
    let mut result = 0.0;
    for (sample_x, sample_y, weight) in taps {
        result += read_sample(input, sample_x, sample_y, contract, edge)? * weight;
    }
    Ok(result)
}

#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_precision_loss,
    reason = "finite footprint bounds are derived from validated affine parameters"
)]
fn area(
    input: &OperationInput<'_>,
    center_x: f64,
    center_y: f64,
    contract: AffineGeometryContract,
    edge: CoverageEdge,
) -> Result<f64, OperationExecutionError> {
    let transform = contract.source_from_output;
    if transform.m12 != 0.0 || transform.m21 != 0.0 {
        return Err(OperationExecutionError::InvalidProduct);
    }
    let footprint_x = transform.m11.abs().max(1.0);
    let footprint_y = transform.m22.abs().max(1.0);
    let left = center_x - footprint_x * 0.5;
    let right = center_x + footprint_x * 0.5;
    let top = center_y - footprint_y * 0.5;
    let bottom = center_y + footprint_y * 0.5;
    let first_x = (left - 0.5).ceil() as i64;
    let last_x = (right + 0.5).floor() as i64;
    let first_y = (top - 0.5).ceil() as i64;
    let last_y = (bottom + 0.5).floor() as i64;
    let mut weighted = 0.0;
    for sample_y in first_y..=last_y {
        let overlap_y =
            (bottom.min(sample_y as f64 + 0.5) - top.max(sample_y as f64 - 0.5)).max(0.0);
        for sample_x in first_x..=last_x {
            let overlap_x =
                (right.min(sample_x as f64 + 0.5) - left.max(sample_x as f64 - 0.5)).max(0.0);
            weighted +=
                read_sample(input, sample_x, sample_y, contract, edge)? * overlap_x * overlap_y;
        }
    }
    Ok(weighted / (footprint_x * footprint_y))
}

fn read_sample(
    input: &OperationInput<'_>,
    mut x: i64,
    mut y: i64,
    contract: AffineGeometryContract,
    edge: CoverageEdge,
) -> Result<f64, OperationExecutionError> {
    let width = i64::try_from(contract.source.width)
        .map_err(|_| OperationExecutionError::InvalidProduct)?;
    let height = i64::try_from(contract.source.height)
        .map_err(|_| OperationExecutionError::InvalidProduct)?;
    if !(0..width).contains(&x) || !(0..height).contains(&y) {
        if edge == CoverageEdge::Transparent {
            return Ok(0.0);
        }
        x = x.clamp(0, width - 1);
        y = y.clamp(0, height - 1);
    }
    let local_x = usize::try_from(x - input.region.origin().x)
        .map_err(|_| OperationExecutionError::InvalidProduct)?;
    let local_y = usize::try_from(y - input.region.origin().y)
        .map_err(|_| OperationExecutionError::InvalidProduct)?;
    let offset = local_y
        .checked_mul(input.product.stride_bytes())
        .and_then(|row| row.checked_add(local_x))
        .ok_or(OperationExecutionError::InvalidProduct)?;
    input
        .product
        .bytes()
        .get(offset)
        .copied()
        .map(f64::from)
        .ok_or(OperationExecutionError::InvalidProduct)
}

#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    reason = "the rounded coverage sample is explicitly clamped to the u8 domain"
)]
fn quantize(sample: f64) -> u8 {
    sample.round().clamp(0.0, 255.0) as u8
}

fn validate(
    request: &OperationRequest,
    input: &OperationInput<'_>,
    output: &OperationOutput<'_>,
    contract: AffineGeometryContract,
) -> Result<(), OperationExecutionError> {
    let format = ProductFormat::Coverage(CoverageFormat::Coverage8);
    if input.port.as_str() != "source"
        || output.port.as_str() != "result"
        || input.product.format() != format
        || output.product.format() != format
        || request.output.format() != Some(format)
        || input.product.size() != input.region.size()
        || output.product.size() != request.output_region.size()
        || output.region != request.output_region
        || contract.validate_output_region(request.output_region).is_err()
    {
        return Err(OperationExecutionError::InvalidProduct);
    }
    Ok(())
}
