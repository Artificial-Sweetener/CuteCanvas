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

//! Responsibility: Execute separable Lanczos3 with reusable row scratch on the CPU.
//!
//! Does not own: graph planning, source storage, coefficient retention, threading, or publication.

use ferrastra_core::{
    ExecutionBudget, OperationExecutionError, OperationInput, OperationOutput, OperationRequest,
    ProductFormat, RasterFormat,
};
use std::collections::{BTreeMap, BTreeSet};

use crate::coefficient_cache::{AxisKey, CoefficientCache};
use crate::lanczos_coefficients::AxisTable;
use crate::raster_color::ColorPipeline;
use crate::sampling_contract::LanczosContract;

struct FilterContext<'a> {
    contract: LanczosContract,
    budget: &'a ExecutionBudget,
    colors: &'a ColorPipeline,
}

pub(crate) fn execute(
    request: &OperationRequest,
    input: &OperationInput<'_>,
    output: &mut OperationOutput<'_>,
    contract: LanczosContract,
    budget: &ExecutionBudget,
    coefficients: &CoefficientCache,
    colors: &ColorPipeline,
) -> Result<(), OperationExecutionError> {
    validate(request, input, output, contract)?;
    if contract.is_identity() {
        return copy_identity(request, input, output, budget);
    }
    let horizontal = coefficients.get_or_build(
        AxisKey::new(
            request.output_region.origin().x,
            request.output_region.size().width,
            contract.horizontal,
        ),
        contract.horizontal,
        budget,
    )?;
    let vertical = coefficients.get_or_build(
        AxisKey::new(
            request.output_region.origin().y,
            request.output_region.size().height,
            contract.vertical,
        ),
        contract.vertical,
        budget,
    )?;
    let context = FilterContext { contract, budget, colors };
    filter_rows(request, input, output, &context, &horizontal, &vertical)
}

fn filter_rows(
    request: &OperationRequest,
    input: &OperationInput<'_>,
    output: &mut OperationOutput<'_>,
    context: &FilterContext<'_>,
    horizontal: &AxisTable,
    vertical: &AxisTable,
) -> Result<(), OperationExecutionError> {
    let width = usize::try_from(request.output_region.size().width)
        .map_err(|_| OperationExecutionError::InvalidProduct)?;
    let height = usize::try_from(request.output_region.size().height)
        .map_err(|_| OperationExecutionError::InvalidProduct)?;
    let stride = output.product.stride_bytes();
    let destination = output.product.bytes_mut();
    let mut rows = BTreeMap::<i64, Vec<[f64; 4]>>::new();
    let mut recycled = Vec::<Vec<[f64; 4]>>::new();
    let input_width = usize::try_from(input.product.size().width)
        .map_err(|_| OperationExecutionError::InvalidProduct)?;
    let mut decoded_source = vec![[0.0_f64; 4]; input_width];
    for output_y in 0..height {
        let vertical_coefficients =
            vertical.get(output_y).ok_or(OperationExecutionError::InvalidProduct)?;
        let required_rows = vertical_coefficients
            .iter()
            .filter_map(|(source_y, _)| source_y)
            .collect::<BTreeSet<_>>();
        recycle_unused_rows(&mut rows, &required_rows, &mut recycled);
        for source_y in &required_rows {
            if !rows.contains_key(source_y) {
                let mut row = recycled.pop().unwrap_or_else(|| vec![[0.0; 4]; width]);
                filter_horizontal_row(
                    input,
                    *source_y,
                    horizontal,
                    context,
                    &mut decoded_source,
                    &mut row,
                )?;
                rows.insert(*source_y, row);
            }
        }
        let row_start =
            output_y.checked_mul(stride).ok_or(OperationExecutionError::InvalidProduct)?;
        let contributing_rows = vertical_coefficients
            .iter()
            .filter_map(|(source_y, weight)| source_y.map(|row| (row, weight)))
            .map(|(source_y, weight)| {
                rows.get(&source_y)
                    .map(|row| (row.as_slice(), weight))
                    .ok_or(OperationExecutionError::InvalidProduct)
            })
            .collect::<Result<Vec<_>, _>>()?;
        write_vertical_row(destination, row_start, width, &contributing_rows, context)?;
    }
    Ok(())
}

fn filter_horizontal_row(
    input: &OperationInput<'_>,
    source_y: i64,
    horizontal: &AxisTable,
    context: &FilterContext<'_>,
    decoded_source: &mut [[f64; 4]],
    destination: &mut [[f64; 4]],
) -> Result<(), OperationExecutionError> {
    if context.budget.should_cancel_now() {
        return Err(OperationExecutionError::Cancelled);
    }
    let input_bytes = input.product.bytes();
    let input_origin_x = input.region.origin().x;
    let row_start = input_row_start(input, source_y)?;
    decode_source_row(input_bytes, row_start, context, decoded_source)?;
    for (output_x, destination_sample) in destination.iter_mut().enumerate() {
        *destination_sample = [0.0; 4];
        let coefficients =
            horizontal.get(output_x).ok_or(OperationExecutionError::InvalidProduct)?;
        for (source_x, weight) in coefficients.iter() {
            let Some(source_x) = source_x else {
                continue;
            };
            let local_x = usize::try_from(source_x - input_origin_x)
                .map_err(|_| OperationExecutionError::InvalidProduct)?;
            let sample =
                decoded_source.get(local_x).ok_or(OperationExecutionError::InvalidProduct)?;
            for channel in 0..4 {
                destination_sample[channel] += sample[channel] * weight;
            }
        }
    }
    Ok(())
}

fn decode_source_row(
    input_bytes: &[u8],
    row_start: usize,
    context: &FilterContext<'_>,
    destination: &mut [[f64; 4]],
) -> Result<(), OperationExecutionError> {
    let row_bytes =
        destination.len().checked_mul(4).ok_or(OperationExecutionError::InvalidProduct)?;
    let row_end =
        row_start.checked_add(row_bytes).ok_or(OperationExecutionError::InvalidProduct)?;
    let source =
        input_bytes.get(row_start..row_end).ok_or(OperationExecutionError::InvalidProduct)?;
    for (sample, bytes) in destination.iter_mut().zip(source.chunks_exact(4)) {
        *sample = context.colors.decode(
            <[u8; 4]>::try_from(bytes).map_err(|_| OperationExecutionError::InvalidProduct)?,
            context.contract.working_space,
        );
    }
    Ok(())
}

fn input_row_start(
    input: &OperationInput<'_>,
    source_y: i64,
) -> Result<usize, OperationExecutionError> {
    usize::try_from(source_y - input.region.origin().y)
        .map_err(|_| OperationExecutionError::InvalidProduct)?
        .checked_mul(input.product.stride_bytes())
        .ok_or(OperationExecutionError::InvalidProduct)
}

fn write_vertical_row(
    destination: &mut [u8],
    row_start: usize,
    width: usize,
    rows: &[(&[[f64; 4]], f64)],
    context: &FilterContext<'_>,
) -> Result<(), OperationExecutionError> {
    for output_x in 0..width {
        if context.budget.should_cancel_now() {
            return Err(OperationExecutionError::Cancelled);
        }
        let mut sample = [0.0_f64; 4];
        for (row, weight) in rows {
            let horizontal = row.get(output_x).ok_or(OperationExecutionError::InvalidProduct)?;
            for channel in 0..4 {
                sample[channel] += horizontal[channel] * weight;
            }
        }
        let encoded = context.colors.encode(sample, context.contract.working_space);
        let offset = row_start
            .checked_add(output_x.checked_mul(4).ok_or(OperationExecutionError::InvalidProduct)?)
            .ok_or(OperationExecutionError::InvalidProduct)?;
        write_sample(destination, offset, encoded)?;
    }
    Ok(())
}

fn copy_identity(
    request: &OperationRequest,
    input: &OperationInput<'_>,
    output: &mut OperationOutput<'_>,
    budget: &ExecutionBudget,
) -> Result<(), OperationExecutionError> {
    let width = usize::try_from(request.output_region.size().width)
        .map_err(|_| OperationExecutionError::InvalidProduct)?;
    let height = usize::try_from(request.output_region.size().height)
        .map_err(|_| OperationExecutionError::InvalidProduct)?;
    let output_stride = output.product.stride_bytes();
    let destination = output.product.bytes_mut();
    for y in 0..height {
        for x in 0..width {
            if budget.should_cancel_now() {
                return Err(OperationExecutionError::Cancelled);
            }
            let source_x = request
                .output_region
                .origin()
                .x
                .checked_add(i64::try_from(x).map_err(|_| OperationExecutionError::InvalidProduct)?)
                .ok_or(OperationExecutionError::InvalidProduct)?;
            let source_y = request
                .output_region
                .origin()
                .y
                .checked_add(i64::try_from(y).map_err(|_| OperationExecutionError::InvalidProduct)?)
                .ok_or(OperationExecutionError::InvalidProduct)?;
            let mut sample = read_sample(input, source_x, source_y)?;
            for channel in 0..3 {
                sample[channel] = sample[channel].min(sample[3]);
            }
            let offset = y
                .checked_mul(output_stride)
                .and_then(|row| x.checked_mul(4).and_then(|column| row.checked_add(column)))
                .ok_or(OperationExecutionError::InvalidProduct)?;
            write_sample(destination, offset, sample)?;
        }
    }
    Ok(())
}

fn recycle_unused_rows(
    rows: &mut BTreeMap<i64, Vec<[f64; 4]>>,
    required: &BTreeSet<i64>,
    recycled: &mut Vec<Vec<[f64; 4]>>,
) {
    let unused = rows.keys().filter(|row| !required.contains(row)).copied().collect::<Vec<_>>();
    for row in unused {
        if let Some(buffer) = rows.remove(&row) {
            recycled.push(buffer);
        }
    }
}

fn read_sample(
    input: &OperationInput<'_>,
    source_x: i64,
    source_y: i64,
) -> Result<[u8; 4], OperationExecutionError> {
    let local_x = usize::try_from(source_x - input.region.origin().x)
        .map_err(|_| OperationExecutionError::InvalidProduct)?;
    let local_y = usize::try_from(source_y - input.region.origin().y)
        .map_err(|_| OperationExecutionError::InvalidProduct)?;
    let offset = local_y
        .checked_mul(input.product.stride_bytes())
        .and_then(|row| local_x.checked_mul(4).and_then(|column| row.checked_add(column)))
        .ok_or(OperationExecutionError::InvalidProduct)?;
    let end = offset.checked_add(4).ok_or(OperationExecutionError::InvalidProduct)?;
    input
        .product
        .bytes()
        .get(offset..end)
        .and_then(|bytes| <[u8; 4]>::try_from(bytes).ok())
        .ok_or(OperationExecutionError::InvalidProduct)
}

fn write_sample(
    destination: &mut [u8],
    offset: usize,
    sample: [u8; 4],
) -> Result<(), OperationExecutionError> {
    let end = offset.checked_add(4).ok_or(OperationExecutionError::InvalidProduct)?;
    destination
        .get_mut(offset..end)
        .ok_or(OperationExecutionError::InvalidProduct)?
        .copy_from_slice(&sample);
    Ok(())
}

fn validate(
    request: &OperationRequest,
    input: &OperationInput<'_>,
    output: &OperationOutput<'_>,
    contract: LanczosContract,
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
