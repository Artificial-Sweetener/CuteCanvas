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

//! Responsibility: Build normalized scale-aware Lanczos3 coefficient tables for output spans.
//!
//! Does not own: raster traversal, color conversion, graph planning, caches, or Python bindings.

use ferrastra_core::{ExecutionBudget, OperationExecutionError};

use crate::sampling_contract::{AxisSampling, map_index};

#[derive(Clone, Debug, PartialEq)]
pub(crate) struct AxisCoefficients {
    samples: Box<[Option<i64>]>,
    weights: Box<[f64]>,
}

impl AxisCoefficients {
    pub(crate) fn iter(&self) -> impl ExactSizeIterator<Item = (Option<i64>, f64)> + '_ {
        self.samples.iter().copied().zip(self.weights.iter().copied())
    }
}

#[derive(Clone, Debug, PartialEq)]
pub(crate) struct AxisTable {
    entries: Box<[AxisCoefficients]>,
}

impl AxisTable {
    pub(crate) fn new(
        output_start: i64,
        output_length: u64,
        sampling: AxisSampling,
        budget: &ExecutionBudget,
    ) -> Result<Self, OperationExecutionError> {
        let output_length =
            usize::try_from(output_length).map_err(|_| OperationExecutionError::InvalidProduct)?;
        let mut entries = Vec::with_capacity(output_length);
        for offset in 0..output_length {
            reject_cancelled(budget)?;
            let output_index = output_start
                .checked_add(
                    i64::try_from(offset).map_err(|_| OperationExecutionError::InvalidProduct)?,
                )
                .ok_or(OperationExecutionError::InvalidProduct)?;
            entries.push(coefficients(output_index, sampling, budget)?);
        }
        Ok(Self { entries: entries.into_boxed_slice() })
    }

    pub(crate) fn get(&self, offset: usize) -> Option<&AxisCoefficients> {
        self.entries.get(offset)
    }

    pub(crate) fn allocated_bytes(&self) -> Result<u64, OperationExecutionError> {
        let entry_bytes = self
            .entries
            .iter()
            .try_fold(0_u64, |total, coefficients| {
                let samples = u64::try_from(coefficients.samples.len())
                    .ok()?
                    .checked_mul(u64::try_from(std::mem::size_of::<Option<i64>>()).ok()?)?;
                let weights = u64::try_from(coefficients.weights.len())
                    .ok()?
                    .checked_mul(u64::try_from(std::mem::size_of::<f64>()).ok()?)?;
                total.checked_add(samples)?.checked_add(weights)
            })
            .ok_or(OperationExecutionError::InvalidProduct)?;
        u64::try_from(self.entries.len())
            .map_err(|_| OperationExecutionError::InvalidProduct)?
            .checked_mul(
                u64::try_from(std::mem::size_of::<AxisCoefficients>())
                    .map_err(|_| OperationExecutionError::InvalidProduct)?,
            )
            .and_then(|headers| headers.checked_add(entry_bytes))
            .ok_or(OperationExecutionError::InvalidProduct)
    }
}

pub(crate) fn scratch_bytes(output_length: u64, sampling: AxisSampling) -> Option<u64> {
    let maximum_taps = sampling.maximum_taps();
    let per_tap =
        u64::try_from(std::mem::size_of::<Option<i64>>() + std::mem::size_of::<f64>()).ok()?;
    let per_entry = u64::try_from(std::mem::size_of::<AxisCoefficients>()).ok()?;
    output_length
        .checked_mul(maximum_taps)?
        .checked_mul(per_tap)?
        .checked_add(output_length.checked_mul(per_entry)?)
}

#[allow(
    clippy::cast_precision_loss,
    reason = "validated sample indices are bounded by widened i32 dimensions and exactly representable in f64"
)]
fn coefficients(
    output_index: i64,
    sampling: AxisSampling,
    budget: &ExecutionBudget,
) -> Result<AxisCoefficients, OperationExecutionError> {
    let center = sampling.source_coordinate(output_index);
    let scale = sampling.filter_scale();
    let (first, last) = sampling.tap_bounds(output_index);
    let capacity =
        usize::try_from(last - first + 1).map_err(|_| OperationExecutionError::InvalidProduct)?;
    let mut samples = Vec::with_capacity(capacity);
    let mut weights = Vec::with_capacity(capacity);
    let mut total = 0.0_f64;
    for source_index in first..=last {
        reject_cancelled(budget)?;
        let weight = lanczos3((center - source_index as f64) * scale);
        samples.push(map_index(source_index, sampling.source_length, sampling.edge));
        weights.push(weight);
        total += weight;
    }
    if !total.is_finite() || total.abs() <= f64::EPSILON {
        return Err(OperationExecutionError::InvalidProduct);
    }
    for weight in &mut weights {
        *weight /= total;
    }
    Ok(AxisCoefficients {
        samples: samples.into_boxed_slice(),
        weights: weights.into_boxed_slice(),
    })
}

fn reject_cancelled(budget: &ExecutionBudget) -> Result<(), OperationExecutionError> {
    if budget.should_cancel_now() { Err(OperationExecutionError::Cancelled) } else { Ok(()) }
}

fn lanczos3(value: f64) -> f64 {
    let distance = value.abs();
    if distance <= f64::EPSILON {
        return 1.0;
    }
    if distance >= 3.0 {
        return 0.0;
    }
    sinc(distance) * sinc(distance / 3.0)
}

fn sinc(value: f64) -> f64 {
    let angle = std::f64::consts::PI * value;
    angle.sin() / angle
}
