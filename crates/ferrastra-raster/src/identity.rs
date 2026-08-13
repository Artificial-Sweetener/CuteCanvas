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

//! Responsibility: Implement exact regional raster identity with bounded cancellation polling.
//!
//! Does not own: source lookup, destination allocation, graph planning, scheduling, or caching.

use ferrastra_core::{
    AlphaMode, AuthoringDescriptor, CancellationContract, CapabilitySet, ComputationDescriptor,
    ConformanceProof, ConformanceRequirements, CostEstimate, EdgeMode, ExecutionBudget,
    ExposureClass, InputDemand, IntRect, Locality, MemoryEstimate, MemoryEstimateError, Operation,
    OperationCategory, OperationContractError, OperationDamageRequest, OperationDescriptor,
    OperationExecutionError, OperationIdentity, OperationInput, OperationKernel, OperationOutput,
    OperationRequest, PortDescriptor, PortDirection, PortId, ProductFormat, ProductSpec,
    QualityTier, RasterFormat, RequestAnalysis, SemanticOperationId, SemanticVersion,
    SupportRadius, WorkingSpace,
};
use std::num::NonZeroU64;

use crate::OperationDefinitionError;

const SEMANTIC_ID: &str = "ferrastra.core.identity";
const SEMANTIC_VERSION: u32 = 1;
const MAXIMUM_POLL_INTERVAL_SAMPLES: NonZeroU64 = match NonZeroU64::new(4_096) {
    Some(value) => value,
    None => NonZeroU64::MIN,
};

/// Exact pass-through operation for typed raster graph and runtime conformance.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IdentityOperation {
    descriptor: OperationDescriptor,
    source_port: PortId,
}

impl IdentityOperation {
    /// Construct and validate the complete built-in identity descriptor.
    ///
    /// # Errors
    ///
    /// Returns [`OperationDefinitionError`] if a static contract declaration is invalid.
    pub fn new() -> Result<Self, OperationDefinitionError> {
        let product = ProductSpec::raster(RasterFormat::Rgba8PremultipliedEncoded);
        let source_port = PortId::new("source")?;
        let descriptor = OperationDescriptor {
            identity: OperationIdentity::new(
                SemanticOperationId::new(SEMANTIC_ID)?,
                SemanticVersion::new(SEMANTIC_VERSION)?,
            ),
            exposure: ExposureClass::PublicGraph,
            category: OperationCategory::Point,
            ports: Box::new([
                PortDescriptor {
                    id: source_port.clone(),
                    direction: PortDirection::Input,
                    product,
                    required: true,
                },
                PortDescriptor {
                    id: PortId::new("result")?,
                    direction: PortDirection::Output,
                    product,
                    required: true,
                },
            ]),
            parameters: Box::default(),
            computation: computation_descriptor(),
            authoring: AuthoringDescriptor {
                summary: "Exact raster identity".into(),
                details: "Copies the requested regional raster samples without numerical change."
                    .into(),
                use_cases: Box::new([
                    "Verify graph, demand, damage, publication, and frontend parity.".into(),
                ]),
                warnings: Box::new([
                    "This operation intentionally performs no image adjustment.".into()
                ]),
            },
            serialization_version: 1,
        };
        descriptor.validate()?;
        Ok(Self { descriptor, source_port })
    }
}

impl Operation for IdentityOperation {
    fn descriptor(&self) -> &OperationDescriptor {
        &self.descriptor
    }

    fn backward_demand(
        &self,
        request: &OperationRequest,
    ) -> Result<Box<[InputDemand]>, OperationContractError> {
        Ok(Box::new([InputDemand {
            port: self.source_port.clone(),
            region: request.output_region,
        }]))
    }

    fn forward_damage(
        &self,
        request: &OperationDamageRequest,
    ) -> Result<IntRect, OperationContractError> {
        Ok(request.input_damage)
    }

    fn memory(&self, request: &OperationRequest) -> Result<MemoryEstimate, MemoryEstimateError> {
        let bytes_per_sample = request
            .output
            .format()
            .map(|format| u64::from(format.bytes_per_sample()))
            .ok_or(MemoryEstimateError::UnsupportedProduct)?;
        let destination_bytes = request
            .output_region
            .size()
            .checked_area()
            .map_err(|_| MemoryEstimateError::Overflow)?
            .checked_mul(bytes_per_sample)
            .ok_or(MemoryEstimateError::Overflow)?;
        Ok(MemoryEstimate { destination_bytes, ..MemoryEstimate::default() })
    }

    fn cancellation(&self) -> CancellationContract {
        CancellationContract {
            maximum_poll_interval_samples: MAXIMUM_POLL_INTERVAL_SAMPLES,
            atomic_exact_publication: true,
        }
    }

    fn conformance(&self) -> ConformanceRequirements {
        ConformanceRequirements::new([
            ConformanceProof::IndependentOracle,
            ConformanceProof::TileEquivalence,
            ConformanceProof::EmptyRegions,
            ConformanceProof::VariedStrides,
            ConformanceProof::CancellationPoints,
            ConformanceProof::CrossFrontend,
        ])
    }

    fn analyze(&self, request: &OperationRequest) -> RequestAnalysis {
        let output_samples = request.output_region.size().checked_area();
        let memory = self.memory(request);
        let accounting_valid = output_samples.is_ok() && memory.is_ok();
        RequestAnalysis {
            valid: request.output == ProductSpec::raster(RasterFormat::Rgba8PremultipliedEncoded)
                && accounting_valid,
            required_capabilities: CapabilitySet::default(),
            locality: Locality::Local,
            support: SupportRadius::default(),
            cost: CostEstimate {
                input_samples: output_samples.unwrap_or_default(),
                output_samples: output_samples.unwrap_or_default(),
                work_units: output_samples.unwrap_or_default(),
            },
            memory: memory.unwrap_or_default(),
            interactive_quality_available: false,
            diagnostics: Box::default(),
        }
    }

    fn quality(&self, quality: QualityTier) -> bool {
        quality == QualityTier::Exact
    }
}

impl OperationKernel for IdentityOperation {
    fn execute(
        &self,
        request: &OperationRequest,
        inputs: &[OperationInput<'_>],
        outputs: &mut [OperationOutput<'_>],
        budget: &ExecutionBudget,
    ) -> Result<(), OperationExecutionError> {
        if inputs.len() != 1 || outputs.len() != 1 {
            return Err(OperationExecutionError::MissingProduct);
        }
        let input = &inputs[0];
        let output = &mut outputs[0];
        if input.port.as_str() != "source"
            || output.port.as_str() != "result"
            || input.region != request.output_region
            || output.region != request.output_region
            || input.product.size() != output.product.size()
            || input.product.format() != output.product.format()
            || request.output.format() != Some(input.product.format())
        {
            return Err(OperationExecutionError::InvalidProduct);
        }
        copy_samples(input.product, &mut output.product, budget)
    }
}

fn copy_samples(
    source: ferrastra_core::ProductView<'_>,
    destination: &mut ferrastra_core::ProductViewMut<'_>,
    budget: &ExecutionBudget,
) -> Result<(), OperationExecutionError> {
    let width = usize::try_from(source.size().width)
        .map_err(|_| OperationExecutionError::InvalidProduct)?;
    let height = usize::try_from(source.size().height)
        .map_err(|_| OperationExecutionError::InvalidProduct)?;
    let bytes_per_sample = usize::from(source.format().bytes_per_sample());
    let row_bytes =
        width.checked_mul(bytes_per_sample).ok_or(OperationExecutionError::InvalidProduct)?;
    let chunk_bytes = usize::try_from(MAXIMUM_POLL_INTERVAL_SAMPLES.get())
        .ok()
        .and_then(|samples| samples.checked_mul(bytes_per_sample))
        .ok_or(OperationExecutionError::InvalidProduct)?;
    let source_stride = source.stride_bytes();
    let destination_stride = destination.stride_bytes();
    let destination_bytes = destination.bytes_mut();
    for row in 0..height {
        let source_start =
            row.checked_mul(source_stride).ok_or(OperationExecutionError::InvalidProduct)?;
        let destination_start =
            row.checked_mul(destination_stride).ok_or(OperationExecutionError::InvalidProduct)?;
        for offset in (0..row_bytes).step_by(chunk_bytes) {
            if budget.should_cancel_now() {
                return Err(OperationExecutionError::Cancelled);
            }
            let count = chunk_bytes.min(row_bytes - offset);
            let source_range = source_start + offset..source_start + offset + count;
            let destination_range = destination_start + offset..destination_start + offset + count;
            let source_chunk =
                source.bytes().get(source_range).ok_or(OperationExecutionError::InvalidProduct)?;
            let destination_chunk = destination_bytes
                .get_mut(destination_range)
                .ok_or(OperationExecutionError::InvalidProduct)?;
            destination_chunk.copy_from_slice(source_chunk);
        }
    }
    Ok(())
}

fn computation_descriptor() -> ComputationDescriptor {
    ComputationDescriptor {
        formats: Box::new([ProductFormat::Raster(RasterFormat::Rgba8PremultipliedEncoded)]),
        alpha_modes: Box::new([AlphaMode::Premultiplied]),
        working_spaces: Box::new([WorkingSpace::SrgbEncoded]),
        edge_modes: Box::new([
            EdgeMode::Clamp,
            EdgeMode::Transparent,
            EdgeMode::Reflect,
            EdgeMode::Wrap,
        ]),
        quality_tiers: Box::new([QualityTier::Exact]),
        locality: Locality::Local,
        support: SupportRadius::default(),
        required_capabilities: CapabilitySet::default(),
        deterministic: true,
        tile_equivalent: true,
    }
}
