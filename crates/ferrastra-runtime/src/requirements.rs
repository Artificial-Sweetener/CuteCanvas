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

//! Responsibility: Plan exact whole-request memory and scratch admission requirements.
//!
//! Does not own: operation memory rules, execution budgets, allocation, source retention, or hosts.

use ferrastra_core::{IntRect, OperationRequest, ProductFormat, ProductSpec, QualityTier};
use ferrastra_graph::{CompiledPlan, GraphName};

use crate::{EvaluationError, OperationSet};

/// Minimum caller budget required to admit one complete regional evaluation.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct EvaluationRequirements {
    /// Peak bytes simultaneously owned while all reachable nodes are evaluated.
    pub memory_bytes: u64,
    /// Peak reusable scratch bytes required by any sequential operation.
    pub scratch_bytes: u64,
}

/// Plan exact memory admission for one named regional request without evaluating it.
///
/// # Errors
///
/// Returns [`EvaluationError`] when demand, parameters, products, or memory cannot be planned.
pub fn evaluation_requirements(
    compiled: &CompiledPlan,
    output_name: &GraphName,
    output_region: IntRect,
    quality: QualityTier,
    operations: &OperationSet,
) -> Result<EvaluationRequirements, EvaluationError> {
    let demands = crate::demand::plan(compiled, output_name, output_region, quality, operations)?;
    let mut retained_bytes = 0_u64;
    let mut requirements = EvaluationRequirements::default();
    for node in compiled.nodes() {
        let Some(demand) = demands.get(&node.node) else {
            continue;
        };
        let product_bytes = packed_bytes(demand.product, demand.region)?;
        if node.definition.source_revision.is_some() {
            retained_bytes = retained_bytes
                .checked_add(product_bytes)
                .ok_or(ferrastra_core::MemoryEstimateError::Overflow)?;
            requirements.memory_bytes = requirements.memory_bytes.max(retained_bytes);
            continue;
        }
        let operation = operations
            .operation(&node.definition.operation)
            .ok_or(EvaluationError::MissingOperation)?;
        let request = OperationRequest {
            output_region: demand.region,
            output: demand.product,
            quality,
            parameters: crate::parameters::resolve(&node.definition, operation.descriptor())?,
        };
        let memory = operation.memory(&request)?;
        let operation_peak = retained_bytes
            .checked_add(memory.checked_peak_bytes()?)
            .ok_or(ferrastra_core::MemoryEstimateError::Overflow)?;
        requirements.memory_bytes = requirements.memory_bytes.max(operation_peak);
        requirements.scratch_bytes = requirements.scratch_bytes.max(memory.scratch_bytes);
        retained_bytes = retained_bytes
            .checked_add(product_bytes)
            .ok_or(ferrastra_core::MemoryEstimateError::Overflow)?;
        requirements.memory_bytes = requirements.memory_bytes.max(retained_bytes);
    }
    Ok(requirements)
}

fn packed_bytes(product: ProductSpec, region: IntRect) -> Result<u64, EvaluationError> {
    let bytes_per_sample = match product.format() {
        Some(ProductFormat::Raster(format)) => format.bytes_per_pixel(),
        Some(ProductFormat::Coverage(format)) => format.bytes_per_sample(),
        None => return Err(EvaluationError::Product),
    };
    region
        .size()
        .checked_area()?
        .checked_mul(u64::from(bytes_per_sample))
        .ok_or(ferrastra_core::MemoryEstimateError::Overflow.into())
}
