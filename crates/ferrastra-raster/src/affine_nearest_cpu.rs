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

//! Responsibility: Execute canonical nearest-neighbor affine RGBA8 sampling on the CPU.
//!
//! Does not own: operation descriptors, source storage, graph policy, or presentation.

use ferrastra_core::{
    EdgeMode, ExecutionBudget, OperationExecutionError, OperationInput, OperationOutput,
    OperationRequest, ProductFormat, RasterFormat,
};

use crate::affine_contract::AffineGeometryContract;
use crate::sampling_contract::map_index;

pub(crate) fn execute(
    request: &OperationRequest,
    input: &OperationInput<'_>,
    output: &mut OperationOutput<'_>,
    contract: AffineGeometryContract,
    edge: EdgeMode,
    budget: &ExecutionBudget,
) -> Result<(), OperationExecutionError> {
    validate(request, input, output, contract)?;
    let width = usize::try_from(request.output_region.size().width)
        .map_err(|_| OperationExecutionError::InvalidProduct)?;
    let height = usize::try_from(request.output_region.size().height)
        .map_err(|_| OperationExecutionError::InvalidProduct)?;
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
            let sample = nearest_sample(input, source.x, source.y, contract, edge)?;
            let offset = local_y
                .checked_mul(stride)
                .and_then(|row| local_x.checked_mul(4).and_then(|column| row.checked_add(column)))
                .ok_or(OperationExecutionError::InvalidProduct)?;
            destination[offset..offset + 4].copy_from_slice(&sample);
        }
    }
    Ok(())
}

#[allow(
    clippy::cast_possible_truncation,
    reason = "finite source coordinates are bounded by validated product dimensions"
)]
fn nearest_sample(
    input: &OperationInput<'_>,
    x: f64,
    y: f64,
    contract: AffineGeometryContract,
    edge: EdgeMode,
) -> Result<[u8; 4], OperationExecutionError> {
    let Some(x) = map_index(x.round() as i64, contract.source.width, edge) else {
        return Ok([0; 4]);
    };
    let Some(y) = map_index(y.round() as i64, contract.source.height, edge) else {
        return Ok([0; 4]);
    };
    let local_x = usize::try_from(x - input.region.origin().x)
        .map_err(|_| OperationExecutionError::InvalidProduct)?;
    let local_y = usize::try_from(y - input.region.origin().y)
        .map_err(|_| OperationExecutionError::InvalidProduct)?;
    let offset = local_y
        .checked_mul(input.product.stride_bytes())
        .and_then(|row| local_x.checked_mul(4).and_then(|column| row.checked_add(column)))
        .ok_or(OperationExecutionError::InvalidProduct)?;
    input
        .product
        .bytes()
        .get(offset..offset + 4)
        .and_then(|sample| <[u8; 4]>::try_from(sample).ok())
        .ok_or(OperationExecutionError::InvalidProduct)
}

fn validate(
    request: &OperationRequest,
    input: &OperationInput<'_>,
    output: &OperationOutput<'_>,
    contract: AffineGeometryContract,
) -> Result<(), OperationExecutionError> {
    let format = ProductFormat::Raster(RasterFormat::Rgba8PremultipliedEncoded);
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
