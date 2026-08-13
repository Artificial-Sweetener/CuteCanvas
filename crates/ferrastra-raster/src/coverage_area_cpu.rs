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

//! Responsibility: Accelerate exact aligned integer Coverage8 area reduction.
//!
//! Does not own: general affine sampling, descriptors, graph policy, or storage.

use ferrastra_core::{
    ExecutionBudget, OperationExecutionError, OperationInput, OperationOutput, OperationRequest,
};

use crate::affine_contract::AffineGeometryContract;

#[derive(Clone, Copy)]
struct AlignedArea {
    scale_x: usize,
    scale_y: usize,
    first_x: i64,
    first_y: i64,
    width: usize,
    height: usize,
}

pub(crate) fn execute_if_aligned(
    request: &OperationRequest,
    input: &OperationInput<'_>,
    output: &mut OperationOutput<'_>,
    contract: AffineGeometryContract,
    budget: &ExecutionBudget,
) -> Result<bool, OperationExecutionError> {
    let Some(area) = aligned_area(request, input, contract)? else {
        return Ok(false);
    };
    let AlignedArea { scale_x, scale_y, first_x, first_y, width, height } = area;
    let source_stride = input.product.stride_bytes();
    let destination_stride = output.product.stride_bytes();
    let source = input.product.bytes();
    let destination = output.product.bytes_mut();
    let sample_count =
        u64::try_from(scale_x.checked_mul(scale_y).ok_or(OperationExecutionError::InvalidProduct)?)
            .map_err(|_| OperationExecutionError::InvalidProduct)?;
    let local_first_x = usize::try_from(first_x - input.region.origin().x)
        .map_err(|_| OperationExecutionError::InvalidProduct)?;
    let local_first_y = usize::try_from(first_y - input.region.origin().y)
        .map_err(|_| OperationExecutionError::InvalidProduct)?;
    for output_y in 0..height {
        let source_y = local_first_y
            .checked_add(
                output_y.checked_mul(scale_y).ok_or(OperationExecutionError::InvalidProduct)?,
            )
            .ok_or(OperationExecutionError::InvalidProduct)?;
        for output_x in 0..width {
            if budget.should_cancel_now() {
                return Err(OperationExecutionError::Cancelled);
            }
            let source_x = local_first_x
                .checked_add(
                    output_x.checked_mul(scale_x).ok_or(OperationExecutionError::InvalidProduct)?,
                )
                .ok_or(OperationExecutionError::InvalidProduct)?;
            let mut sum = 0_u64;
            for row in source_y..source_y + scale_y {
                let start = row
                    .checked_mul(source_stride)
                    .and_then(|offset| offset.checked_add(source_x))
                    .ok_or(OperationExecutionError::InvalidProduct)?;
                let end =
                    start.checked_add(scale_x).ok_or(OperationExecutionError::InvalidProduct)?;
                let samples =
                    source.get(start..end).ok_or(OperationExecutionError::InvalidProduct)?;
                sum += samples.iter().map(|sample| u64::from(*sample)).sum::<u64>();
            }
            let offset = output_y
                .checked_mul(destination_stride)
                .and_then(|row| row.checked_add(output_x))
                .ok_or(OperationExecutionError::InvalidProduct)?;
            destination[offset] = u8::try_from((sum + sample_count / 2) / sample_count)
                .map_err(|_| OperationExecutionError::InvalidProduct)?;
        }
    }
    Ok(true)
}

fn aligned_area(
    request: &OperationRequest,
    input: &OperationInput<'_>,
    contract: AffineGeometryContract,
) -> Result<Option<AlignedArea>, OperationExecutionError> {
    let transform = contract.source_from_output;
    let Some(scale_x) = integer_scale(transform.m11) else {
        return Ok(None);
    };
    let Some(scale_y) = integer_scale(transform.m22) else {
        return Ok(None);
    };
    if transform.m12 != 0.0 || transform.m21 != 0.0 {
        return Ok(None);
    }
    let first_center = contract
        .source_coordinate(request.output_region.origin().x, request.output_region.origin().y);
    let Some(first_x) = integer_coordinate(first_center.x - transform.m11 * 0.5 + 0.5) else {
        return Ok(None);
    };
    let Some(first_y) = integer_coordinate(first_center.y - transform.m22 * 0.5 + 0.5) else {
        return Ok(None);
    };
    let width = usize::try_from(request.output_region.size().width)
        .map_err(|_| OperationExecutionError::InvalidProduct)?;
    let height = usize::try_from(request.output_region.size().height)
        .map_err(|_| OperationExecutionError::InvalidProduct)?;
    let source_width = i64::try_from(contract.source.width)
        .map_err(|_| OperationExecutionError::InvalidProduct)?;
    let source_height = i64::try_from(contract.source.height)
        .map_err(|_| OperationExecutionError::InvalidProduct)?;
    let sampled_width =
        width.checked_mul(scale_x).ok_or(OperationExecutionError::InvalidProduct)?;
    let sampled_height =
        height.checked_mul(scale_y).ok_or(OperationExecutionError::InvalidProduct)?;
    let sampled_right = first_x
        .checked_add(
            i64::try_from(sampled_width).map_err(|_| OperationExecutionError::InvalidProduct)?,
        )
        .ok_or(OperationExecutionError::InvalidProduct)?;
    let sampled_bottom = first_y
        .checked_add(
            i64::try_from(sampled_height).map_err(|_| OperationExecutionError::InvalidProduct)?,
        )
        .ok_or(OperationExecutionError::InvalidProduct)?;
    let input_right = input.region.origin().x
        + i64::try_from(input.region.size().width)
            .map_err(|_| OperationExecutionError::InvalidProduct)?;
    let input_bottom = input.region.origin().y
        + i64::try_from(input.region.size().height)
            .map_err(|_| OperationExecutionError::InvalidProduct)?;
    if first_x < 0
        || first_y < 0
        || sampled_right > source_width
        || sampled_bottom > source_height
        || first_x < input.region.origin().x
        || first_y < input.region.origin().y
        || sampled_right > input_right
        || sampled_bottom > input_bottom
    {
        return Ok(None);
    }
    Ok(Some(AlignedArea { scale_x, scale_y, first_x, first_y, width, height }))
}

#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    reason = "the validated integer scale is finite, positive, and i32-bounded"
)]
fn integer_scale(value: f64) -> Option<usize> {
    if !value.is_finite() || value < 1.0 || value > f64::from(i32::MAX) {
        return None;
    }
    let rounded = value.round();
    ((value - rounded).abs() <= 1.0e-12).then_some(rounded as usize)
}

#[allow(
    clippy::cast_possible_truncation,
    reason = "the validated integer coordinate is finite and i32-bounded"
)]
fn integer_coordinate(value: f64) -> Option<i64> {
    if !value.is_finite() || value < f64::from(i32::MIN) || value > f64::from(i32::MAX) {
        return None;
    }
    let rounded = value.round();
    ((value - rounded).abs() <= 1.0e-9).then_some(rounded as i64)
}
