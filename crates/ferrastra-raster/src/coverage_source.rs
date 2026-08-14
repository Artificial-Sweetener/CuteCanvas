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

//! Responsibility: Define the typed spatial contract for immutable Coverage8 revisions.
//!
//! Does not own: source storage, graph bindings, scheduling, sampling, or copying.

use std::num::NonZeroU64;

use ferrastra_core::{
    AlphaMode, AuthoringDescriptor, CancellationContract, CapabilitySet, ComputationDescriptor,
    ConformanceProof, ConformanceRequirements, CostEstimate, CoverageFormat, EdgeMode,
    ExposureClass, InputDemand, IntRect, Locality, MemoryEstimate, MemoryEstimateError, Operation,
    OperationCategory, OperationContractError, OperationDamageRequest, OperationDescriptor,
    OperationIdentity, OperationRequest, PortDescriptor, PortDirection, PortId, ProductFormat,
    ProductSpec, QualityTier, RequestAnalysis, SemanticOperationId, SemanticVersion, SupportRadius,
    WorkingSpace,
};

const SEMANTIC_ID: &str = "ferrastra.source.coverage";
const SEMANTIC_VERSION: u32 = 1;

use crate::OperationDefinitionError;

/// Immutable Coverage8 source operation resolved by the runtime source adapter.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CoverageSourceOperation {
    descriptor: OperationDescriptor,
}

impl CoverageSourceOperation {
    /// Construct and validate the complete coverage source descriptor.
    ///
    /// # Errors
    ///
    /// Returns [`OperationDefinitionError`] if a static declaration is invalid.
    pub fn new() -> Result<Self, OperationDefinitionError> {
        let product = ProductSpec::coverage(CoverageFormat::Coverage8);
        let descriptor = OperationDescriptor {
            identity: OperationIdentity::new(
                SemanticOperationId::new(SEMANTIC_ID)?,
                SemanticVersion::new(SEMANTIC_VERSION)?,
            ),
            exposure: ExposureClass::HostOnly,
            category: OperationCategory::Generator,
            ports: Box::new([PortDescriptor {
                id: PortId::new("result")?,
                direction: PortDirection::Output,
                product,
                required: true,
            }]),
            parameters: Box::default(),
            computation: ComputationDescriptor {
                formats: Box::new([ProductFormat::Coverage(CoverageFormat::Coverage8)]),
                alpha_modes: Box::new([AlphaMode::Opaque]),
                working_spaces: Box::new([WorkingSpace::SrgbLinear]),
                edge_modes: Box::new([EdgeMode::Transparent]),
                quality_tiers: Box::new([QualityTier::Exact]),
                locality: Locality::Generator,
                support: SupportRadius::default(),
                required_capabilities: CapabilitySet::default(),
                deterministic: true,
                tile_equivalent: true,
            },
            authoring: AuthoringDescriptor {
                summary: "Immutable coverage source".into(),
                details:
                    "Provides exact regional Coverage8 samples from one retained native revision."
                        .into(),
                use_cases: Box::new([
                    "Bind host-owned immutable masks and coverage fields to a graph.".into(),
                ]),
                warnings: Box::new([
                    "The source revision must remain available for the complete evaluation.".into(),
                ]),
            },
            serialization_version: 1,
        };
        descriptor.validate()?;
        Ok(Self { descriptor })
    }
}

impl Operation for CoverageSourceOperation {
    fn descriptor(&self) -> &OperationDescriptor {
        &self.descriptor
    }

    fn backward_demand(
        &self,
        _request: &OperationRequest,
    ) -> Result<Box<[InputDemand]>, OperationContractError> {
        Ok(Box::default())
    }

    fn forward_damage(
        &self,
        request: &OperationDamageRequest,
    ) -> Result<IntRect, OperationContractError> {
        Ok(request.input_damage)
    }

    fn memory(&self, request: &OperationRequest) -> Result<MemoryEstimate, MemoryEstimateError> {
        if request.output != ProductSpec::coverage(CoverageFormat::Coverage8) {
            return Err(MemoryEstimateError::UnsupportedProduct);
        }
        let destination_bytes = request
            .output_region
            .size()
            .checked_area()
            .map_err(|_| MemoryEstimateError::Overflow)?;
        Ok(MemoryEstimate { destination_bytes, ..MemoryEstimate::default() })
    }

    fn cancellation(&self) -> CancellationContract {
        CancellationContract {
            maximum_poll_interval_samples: NonZeroU64::MIN,
            atomic_exact_publication: true,
        }
    }

    fn conformance(&self) -> ConformanceRequirements {
        ConformanceRequirements::new([
            ConformanceProof::EmptyRegions,
            ConformanceProof::VariedStrides,
            ConformanceProof::CrossFrontend,
        ])
    }

    fn analyze(&self, request: &OperationRequest) -> RequestAnalysis {
        let memory = self.memory(request);
        let output_samples = request.output_region.size().checked_area().unwrap_or_default();
        RequestAnalysis {
            valid: memory.is_ok() && request.quality == QualityTier::Exact,
            required_capabilities: CapabilitySet::default(),
            locality: Locality::Generator,
            support: SupportRadius::default(),
            cost: CostEstimate { input_samples: 0, output_samples, work_units: output_samples },
            memory: memory.unwrap_or_default(),
            interactive_quality_available: false,
            diagnostics: Box::default(),
        }
    }

    fn quality(&self, quality: QualityTier) -> bool {
        quality == QualityTier::Exact
    }
}
