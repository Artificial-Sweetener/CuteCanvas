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

//! Responsibility: Declare canonical range-preserving affine sampling for Coverage8 fields.
//!
//! Does not own: source storage, viewport policy, document policy, or scheduling.

use std::num::NonZeroU64;

use ferrastra_core::{
    AlphaMode, AuthoringDescriptor, CancellationContract, CapabilitySet, ComputationDescriptor,
    ConformanceProof, ConformanceRequirements, CostEstimate, CoverageFormat, EdgeMode,
    ExecutionBudget, InputDemand, IntRect, MemoryEstimate, MemoryEstimateError, Operation,
    OperationCategory, OperationContractError, OperationDamageRequest, OperationDescriptor,
    OperationExecutionError, OperationIdentity, OperationInput, OperationKernel, OperationOutput,
    OperationRequest, ParameterDescriptor, ParameterId, ParameterRange, ParameterType,
    ParameterValue, PortDescriptor, PortDirection, PortId, ProductFormat, ProductSpec, QualityTier,
    RequestAnalysis, SemanticOperationId, SemanticVersion, SupportRadius, Unit, WorkingSpace,
};

use crate::affine_contract::AffineGeometryContract;
use crate::coverage_affine_cpu::{CoverageEdge, CoverageFilter};
use crate::sampling_contract::{MAX_DIMENSION, edge_mode};
use crate::{OperationDefinitionError, coverage_affine_cpu};

const SEMANTIC_ID: &str = "ferrastra.resample.coverage-affine";
const SEMANTIC_VERSION: u32 = 1;

/// Exact range-preserving affine sampling for scalar Coverage8 products.
#[derive(Clone, Debug)]
pub struct CoverageAffineOperation {
    descriptor: OperationDescriptor,
    source_port: PortId,
}

impl CoverageAffineOperation {
    /// Construct and validate the complete coverage sampling descriptor.
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
                summary: "Affine Coverage8 sampling".into(),
                details: "Samples scalar coverage through an explicit output-to-source affine transform with transparent edges and range-preserving linear interpolation.".into(),
                use_cases: Box::new([
                    "Project masks and coverage fields into explicit destination-coordinate storage."
                        .into(),
                ]),
                warnings: Box::default(),
            },
            serialization_version: 1,
        };
        descriptor.validate()?;
        Ok(Self { descriptor, source_port: PortId::new("source")? })
    }
}

impl Operation for CoverageAffineOperation {
    fn descriptor(&self) -> &OperationDescriptor {
        &self.descriptor
    }

    fn backward_demand(
        &self,
        request: &OperationRequest,
    ) -> Result<Box<[InputDemand]>, OperationContractError> {
        let contract = AffineGeometryContract::from_parameters(&request.parameters)?;
        let region = if coverage_filter(&request.parameters)? == CoverageFilter::Area {
            contract.source_area_demand(request.output_region)?
        } else {
            contract.source_demand(request.output_region)?
        };
        Ok(Box::new([InputDemand { port: self.source_port.clone(), region }]))
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
        if request.output != ProductSpec::coverage(CoverageFormat::Coverage8) {
            return Err(MemoryEstimateError::UnsupportedProduct);
        }
        AffineGeometryContract::from_parameters(&request.parameters)
            .and_then(|contract| contract.validate_output_region(request.output_region))
            .map_err(|_| MemoryEstimateError::InvalidParameters)?;
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
            .and_then(|contract| contract.source_demand(request.output_region))
            .ok()
            .and_then(|region| region.size().checked_area().ok())
            .unwrap_or_default();
        RequestAnalysis {
            valid: memory.is_ok() && request.quality == QualityTier::Exact,
            required_capabilities: CapabilitySet::default(),
            locality: ferrastra_core::Locality::Transform,
            support: SupportRadius { x: 1, y: 1 },
            cost: CostEstimate {
                input_samples,
                output_samples,
                work_units: output_samples.saturating_mul(4),
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

impl OperationKernel for CoverageAffineOperation {
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
        let filter = coverage_filter(&request.parameters)
            .map_err(|_| OperationExecutionError::InvalidProduct)?;
        let edge = coverage_edge(&request.parameters)
            .map_err(|_| OperationExecutionError::InvalidProduct)?;
        coverage_affine_cpu::execute(
            request,
            &inputs[0],
            &mut outputs[0],
            contract,
            filter,
            edge,
            budget,
        )
    }
}

fn ports() -> Result<Box<[PortDescriptor]>, OperationDefinitionError> {
    let product = ProductSpec::coverage(CoverageFormat::Coverage8);
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
    values.push(ParameterDescriptor {
        id: ParameterId::new("filter")?,
        parameter_type: ParameterType::Enum,
        unit: Unit::Unitless,
        default: ParameterValue::Enum(ParameterId::new("linear")?),
        hard_range: None,
        recommended_range: None,
        enum_values: ["nearest", "linear", "area"]
            .into_iter()
            .map(ParameterId::new)
            .collect::<Result<Vec<_>, _>>()?
            .into_boxed_slice(),
    });
    values.push(ParameterDescriptor {
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
    });
    Ok(values)
}

fn coverage_filter(
    parameters: &ferrastra_core::OperationParameters,
) -> Result<CoverageFilter, OperationContractError> {
    let Some(ParameterValue::Enum(value)) = parameters.get_named("filter") else {
        return Err(OperationContractError::InvalidParameters);
    };
    match value.as_str() {
        "nearest" => Ok(CoverageFilter::Nearest),
        "linear" => Ok(CoverageFilter::Linear),
        "area" => Ok(CoverageFilter::Area),
        _ => Err(OperationContractError::InvalidParameters),
    }
}

fn coverage_edge(
    parameters: &ferrastra_core::OperationParameters,
) -> Result<CoverageEdge, OperationContractError> {
    let Some(ParameterValue::Enum(value)) = parameters.get_named("edge_mode") else {
        return Err(OperationContractError::InvalidParameters);
    };
    match value.as_str() {
        "transparent" => Ok(CoverageEdge::Transparent),
        "clamp" => Ok(CoverageEdge::Clamp),
        _ => Err(OperationContractError::InvalidParameters),
    }
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
        formats: Box::new([ProductFormat::Coverage(CoverageFormat::Coverage8)]),
        alpha_modes: Box::new([AlphaMode::Opaque]),
        working_spaces: Box::new([WorkingSpace::SrgbLinear]),
        edge_modes: Box::new([EdgeMode::Transparent, EdgeMode::Clamp]),
        quality_tiers: Box::new([QualityTier::Exact]),
        locality: ferrastra_core::Locality::Transform,
        support: SupportRadius { x: MAX_DIMENSION as u64, y: MAX_DIMENSION as u64 },
        required_capabilities: CapabilitySet::default(),
        deterministic: true,
        tile_equivalent: true,
    }
}
