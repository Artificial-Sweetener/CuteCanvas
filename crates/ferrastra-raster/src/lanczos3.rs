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

//! Responsibility: Declare the canonical whole-raster Lanczos3 resize operation.
//!
//! Does not own: sampling execution, source storage, graph construction, scheduling, or Qt.

use ferrastra_core::{
    AuthoringDescriptor, ExecutionBudget, InputDemand, IntRect, MemoryEstimate,
    MemoryEstimateError, Operation, OperationContractError, OperationDamageRequest,
    OperationDescriptor, OperationExecutionError, OperationInput, OperationKernel, OperationOutput,
    OperationRequest, QualityTier, RequestAnalysis,
};

use crate::OperationDefinitionError;
use crate::lanczos_operation::{
    LanczosImplementation, computation_descriptor, ports, resize_parameters,
};
use crate::sampling_contract::LanczosContract;

const SEMANTIC_ID: &str = "ferrastra.resample.lanczos3";
const SEMANTIC_VERSION: u32 = 1;

/// Canonical three-lobe axis-aligned resize operation for premultiplied RGBA8 rasters.
#[derive(Clone, Debug)]
pub struct Lanczos3Operation {
    implementation: LanczosImplementation,
}

impl Lanczos3Operation {
    /// Construct and validate the complete built-in Lanczos3 resize descriptor.
    ///
    /// # Errors
    ///
    /// Returns [`OperationDefinitionError`] if a static contract declaration is invalid.
    pub fn new() -> Result<Self, OperationDefinitionError> {
        let descriptor = OperationDescriptor {
            identity: crate::lanczos_operation::identity(SEMANTIC_ID, SEMANTIC_VERSION)?,
            exposure: ferrastra_core::ExposureClass::PublicGraph,
            category: ferrastra_core::OperationCategory::Transform,
            ports: ports()?,
            parameters: resize_parameters()?.into_boxed_slice(),
            computation: computation_descriptor(),
            authoring: AuthoringDescriptor {
                summary: "Scale-aware Lanczos3 resize".into(),
                details: "Resizes premultiplied RGBA8 rasters with pixel-center mapping, a normalized three-lobe sinc window, and widened minification support.".into(),
                use_cases: Box::new([
                    "Build high-quality image pyramid levels and exact axis-aligned resized products."
                        .into(),
                ]),
                warnings: Box::new([
                    "Negative filter lobes can ring around high-contrast edges; use a locally bounded sampler when ringing is unacceptable."
                        .into(),
                ]),
            },
            serialization_version: 1,
        };
        descriptor.validate()?;
        Ok(Self {
            implementation: LanczosImplementation::new(
                descriptor,
                LanczosContract::from_resize_parameters,
            )?,
        })
    }
}

impl Operation for Lanczos3Operation {
    fn descriptor(&self) -> &OperationDescriptor {
        self.implementation.descriptor()
    }

    fn backward_demand(
        &self,
        request: &OperationRequest,
    ) -> Result<Box<[InputDemand]>, OperationContractError> {
        self.implementation.backward_demand(request)
    }

    fn forward_damage(
        &self,
        request: &OperationDamageRequest,
    ) -> Result<IntRect, OperationContractError> {
        self.implementation.forward_damage(request)
    }

    fn memory(&self, request: &OperationRequest) -> Result<MemoryEstimate, MemoryEstimateError> {
        self.implementation.memory(request)
    }

    fn cancellation(&self) -> ferrastra_core::CancellationContract {
        LanczosImplementation::cancellation()
    }

    fn conformance(&self) -> ferrastra_core::ConformanceRequirements {
        LanczosImplementation::conformance()
    }

    fn analyze(&self, request: &OperationRequest) -> RequestAnalysis {
        self.implementation.analyze(request)
    }

    fn quality(&self, quality: QualityTier) -> bool {
        LanczosImplementation::quality(quality)
    }
}

impl OperationKernel for Lanczos3Operation {
    fn execute(
        &self,
        request: &OperationRequest,
        inputs: &[OperationInput<'_>],
        outputs: &mut [OperationOutput<'_>],
        budget: &ExecutionBudget,
    ) -> Result<(), OperationExecutionError> {
        self.implementation.execute(request, inputs, outputs, budget)
    }
}

impl PartialEq for Lanczos3Operation {
    fn eq(&self, other: &Self) -> bool {
        self.implementation == other.implementation
    }
}

impl Eq for Lanczos3Operation {}
