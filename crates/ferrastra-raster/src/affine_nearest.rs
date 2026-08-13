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

//! Responsibility: Declare canonical nearest-neighbor affine sampling for RGBA8 rasters.
//!
//! Does not own: source storage, viewport policy, document policy, or scheduling.

use std::num::NonZeroU64;

use ferrastra_core::{
    AlphaMode, AuthoringDescriptor, CancellationContract, CapabilitySet, ComputationDescriptor,
    ConformanceProof, ConformanceRequirements, CostEstimate, EdgeMode, ExecutionBudget,
    InputDemand, IntRect, MemoryEstimate, MemoryEstimateError, Operation, OperationCategory,
    OperationContractError, OperationDamageRequest, OperationDescriptor, OperationExecutionError,
    OperationIdentity, OperationInput, OperationKernel, OperationOutput, OperationRequest,
    ParameterDescriptor, ParameterId, ParameterRange, ParameterType, ParameterValue,
    PortDescriptor, PortDirection, PortId, ProductFormat, ProductSpec, QualityTier, RasterFormat,
    RequestAnalysis, SemanticOperationId, SemanticVersion, SupportRadius, Unit, WorkingSpace,
};

use crate::affine_contract::AffineGeometryContract;

const SEMANTIC_ID: &str = "ferrastra.resample.affine-nearest";
const SEMANTIC_VERSION: u32 = 1;
use crate::sampling_contract::{MAX_DIMENSION, edge_mode};
use crate::{OperationDefinitionError, affine_nearest_cpu};

/// Exact nearest-neighbor sampling through an output-to-source affine transform.
#[derive(Clone, Debug)]
pub struct AffineNearestOperation {
    descriptor: OperationDescriptor,
    source_port: PortId,
}

impl AffineNearestOperation {
    /// Construct and validate the complete nearest-neighbor descriptor.
    ///
    /// # Errors
    ///
    /// Returns [`OperationDefinitionError`] if a static declaration is invalid.
    pub fn new() -> Result<Self, OperationDefinitionError> {
        let descriptor = OperationDescriptor {
            identity: OperationIdentity::new(
                SemanticOperationId::new(SEMANTIC_ID)?,
                SemanticVersion::new(SEMANTIC_VERSION)?,
            ),
            exposure: ferrastra_core::ExposureClass::PublicGraph,
            category: OperationCategory::Transform,
            ports: ports()?,
            parameters: parameters()?.into_boxed_slice(),
            computation: computation_descriptor(),
            authoring: AuthoringDescriptor {
                summary: "Affine nearest-neighbor raster sampling".into(),
                details: "Selects premultiplied RGBA8 pixels through an explicit output-to-source affine transform with explicit transparent or clamped edges.".into(),
                use_cases: Box::new([
                    "Project pixel-art and discrete raster fields without interpolation.".into(),
                ]),
                warnings: Box::new([
                    "Nearest-neighbor minification can alias high-frequency source detail.".into(),
                ]),
            },
            serialization_version: 1,
        };
        descriptor.validate()?;
        Ok(Self { descriptor, source_port: PortId::new("source")? })
    }
}

impl Operation for AffineNearestOperation {
    fn descriptor(&self) -> &OperationDescriptor {
        &self.descriptor
    }

    fn backward_demand(
        &self,
        request: &OperationRequest,
    ) -> Result<Box<[InputDemand]>, OperationContractError> {
        let contract = AffineGeometryContract::from_parameters(&request.parameters)?;
        Ok(Box::new([InputDemand {
            port: self.source_port.clone(),
            region: contract
                .source_demand_with_edge(request.output_region, edge_mode(&request.parameters)?)?,
        }]))
    }

    fn forward_damage(
        &self,
        request: &OperationDamageRequest,
    ) -> Result<IntRect, OperationContractError> {
        if request.input != self.source_port {
            return Err(OperationContractError::InvalidParameters);
        }
        AffineGeometryContract::from_parameters(&request.parameters)?
            .forward_damage(request.input_damage, edge_mode(&request.parameters)?)
    }

    fn memory(&self, request: &OperationRequest) -> Result<MemoryEstimate, MemoryEstimateError> {
        if request.output != ProductSpec::raster(RasterFormat::Rgba8PremultipliedEncoded) {
            return Err(MemoryEstimateError::UnsupportedProduct);
        }
        AffineGeometryContract::from_parameters(&request.parameters)
            .and_then(|contract| contract.validate_output_region(request.output_region))
            .map_err(|_| MemoryEstimateError::InvalidParameters)?;
        let destination_bytes = request
            .output_region
            .size()
            .checked_area()
            .map_err(|_| MemoryEstimateError::Overflow)?
            .checked_mul(4)
            .ok_or(MemoryEstimateError::Overflow)?;
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
            ConformanceProof::IndependentOracle,
            ConformanceProof::TileEquivalence,
            ConformanceProof::EmptyRegions,
            ConformanceProof::VariedStrides,
            ConformanceProof::CancellationPoints,
            ConformanceProof::CrossFrontend,
        ])
    }

    fn analyze(&self, request: &OperationRequest) -> RequestAnalysis {
        let contract = AffineGeometryContract::from_parameters(&request.parameters);
        let memory = self.memory(request);
        let output_samples = request.output_region.size().checked_area().unwrap_or_default();
        let input_samples = contract
            .and_then(|contract| {
                contract
                    .source_demand_with_edge(request.output_region, edge_mode(&request.parameters)?)
            })
            .ok()
            .and_then(|region| region.size().checked_area().ok())
            .unwrap_or_default();
        RequestAnalysis {
            valid: memory.is_ok() && request.quality == QualityTier::Exact,
            required_capabilities: CapabilitySet::default(),
            locality: ferrastra_core::Locality::Transform,
            support: SupportRadius::default(),
            cost: CostEstimate { input_samples, output_samples, work_units: output_samples },
            memory: memory.unwrap_or_default(),
            interactive_quality_available: false,
            diagnostics: Box::default(),
        }
    }

    fn quality(&self, quality: QualityTier) -> bool {
        quality == QualityTier::Exact
    }
}

impl OperationKernel for AffineNearestOperation {
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
        let contract = AffineGeometryContract::from_parameters(&request.parameters)
            .map_err(|_| OperationExecutionError::InvalidProduct)?;
        let edge =
            edge_mode(&request.parameters).map_err(|_| OperationExecutionError::InvalidProduct)?;
        affine_nearest_cpu::execute(request, &inputs[0], &mut outputs[0], contract, edge, budget)
    }
}

fn ports() -> Result<Box<[PortDescriptor]>, OperationDefinitionError> {
    let product = ProductSpec::raster(RasterFormat::Rgba8PremultipliedEncoded);
    Ok(Box::new([
        PortDescriptor {
            id: PortId::new("source")?,
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
    ]))
}

fn parameters() -> Result<Vec<ParameterDescriptor>, OperationDefinitionError> {
    let mut values = vec![
        dimension_parameter("source_width")?,
        dimension_parameter("source_height")?,
        dimension_parameter("destination_width")?,
        dimension_parameter("destination_height")?,
    ];
    for (id, default) in [
        ("source_m11", 1.0),
        ("source_m12", 0.0),
        ("source_m21", 0.0),
        ("source_m22", 1.0),
        ("source_tx", 0.0),
        ("source_ty", 0.0),
    ] {
        values.push(ParameterDescriptor {
            id: ParameterId::new(id)?,
            parameter_type: ParameterType::Scalar,
            unit: Unit::Unitless,
            default: ParameterValue::Scalar(ferrastra_core::FiniteScalar::new(default)?),
            hard_range: None,
            recommended_range: None,
            enum_values: Box::default(),
        });
    }
    values.push(edge_parameter()?);
    Ok(values)
}

fn edge_parameter() -> Result<ParameterDescriptor, OperationDefinitionError> {
    Ok(ParameterDescriptor {
        id: ParameterId::new("edge_mode")?,
        parameter_type: ParameterType::Enum,
        unit: Unit::Unitless,
        default: ParameterValue::Enum(ParameterId::new("transparent")?),
        hard_range: None,
        recommended_range: None,
        enum_values: ["transparent", "clamp"]
            .into_iter()
            .map(ParameterId::new)
            .collect::<Result<Vec<_>, _>>()?
            .into_boxed_slice(),
    })
}

fn dimension_parameter(id: &str) -> Result<ParameterDescriptor, OperationDefinitionError> {
    Ok(ParameterDescriptor {
        id: ParameterId::new(id)?,
        parameter_type: ParameterType::Integer,
        unit: Unit::Pixels,
        default: ParameterValue::Integer(1),
        hard_range: Some(ParameterRange::integer(1, MAX_DIMENSION)?),
        recommended_range: None,
        enum_values: Box::default(),
    })
}

fn computation_descriptor() -> ComputationDescriptor {
    ComputationDescriptor {
        formats: Box::new([ProductFormat::Raster(RasterFormat::Rgba8PremultipliedEncoded)]),
        alpha_modes: Box::new([AlphaMode::Premultiplied]),
        working_spaces: Box::new([WorkingSpace::SrgbEncoded, WorkingSpace::SrgbLinear]),
        edge_modes: Box::new([EdgeMode::Transparent, EdgeMode::Clamp]),
        quality_tiers: Box::new([QualityTier::Exact]),
        locality: ferrastra_core::Locality::Transform,
        support: SupportRadius { x: MAX_DIMENSION as u64, y: MAX_DIMENSION as u64 },
        required_capabilities: CapabilitySet::default(),
        deterministic: true,
        tile_equivalent: true,
    }
}
