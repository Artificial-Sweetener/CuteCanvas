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

//! Responsibility: Execute shared canonical Lanczos3 operation behavior from typed contracts.
//!
//! Does not own: operation-specific identities, authoring descriptions, graph policy, or Qt.

use std::num::NonZeroU64;
use std::sync::Arc;

use ferrastra_core::{
    AlphaMode, CancellationContract, CapabilitySet, ComputationDescriptor, ConformanceProof,
    ConformanceRequirements, CostEstimate, EdgeMode, ExecutionBudget, InputDemand, IntRect,
    Locality, MemoryEstimate, MemoryEstimateError, OperationContractError, OperationDamageRequest,
    OperationDescriptor, OperationExecutionError, OperationIdentity, OperationInput,
    OperationOutput, OperationParameters, OperationRequest, ParameterDescriptor, ParameterId,
    ParameterRange, ParameterType, ParameterValue, PortDescriptor, PortDirection, PortId,
    ProductFormat, ProductSpec, QualityTier, RasterFormat, RequestAnalysis, SemanticOperationId,
    SemanticVersion, SupportRadius, Unit, WorkingSpace,
};

use crate::coefficient_cache::CoefficientCache;
use crate::lanczos_coefficients;
use crate::raster_color::ColorPipeline;
use crate::sampling_contract::{LanczosContract, MAX_DIMENSION};
use crate::{OperationDefinitionError, lanczos_cpu};

const MAXIMUM_POLL_INTERVAL_SAMPLES: NonZeroU64 = NonZeroU64::MIN;
const COEFFICIENT_CACHE_BYTES: u64 = 16 * 1024 * 1024;
type ContractParser = fn(&OperationParameters) -> Result<LanczosContract, OperationContractError>;

#[derive(Clone, Debug)]
pub(crate) struct LanczosImplementation {
    descriptor: OperationDescriptor,
    source_port: PortId,
    coefficients: Arc<CoefficientCache>,
    colors: Arc<ColorPipeline>,
    parse_contract: ContractParser,
}

impl LanczosImplementation {
    pub(crate) fn new(
        descriptor: OperationDescriptor,
        parse_contract: ContractParser,
    ) -> Result<Self, OperationDefinitionError> {
        Ok(Self {
            descriptor,
            source_port: PortId::new("source")?,
            coefficients: Arc::new(CoefficientCache::new(COEFFICIENT_CACHE_BYTES)),
            colors: Arc::new(ColorPipeline::new()),
            parse_contract,
        })
    }

    pub(crate) fn descriptor(&self) -> &OperationDescriptor {
        &self.descriptor
    }

    pub(crate) fn backward_demand(
        &self,
        request: &OperationRequest,
    ) -> Result<Box<[InputDemand]>, OperationContractError> {
        let contract = (self.parse_contract)(&request.parameters)?;
        Ok(Box::new([InputDemand {
            port: self.source_port.clone(),
            region: contract.source_demand(request.output_region)?,
        }]))
    }

    pub(crate) fn forward_damage(
        &self,
        request: &OperationDamageRequest,
    ) -> Result<IntRect, OperationContractError> {
        if request.input != self.source_port {
            return Err(OperationContractError::InvalidParameters);
        }
        (self.parse_contract)(&request.parameters)?.forward_damage(request.input_damage)
    }

    pub(crate) fn memory(
        &self,
        request: &OperationRequest,
    ) -> Result<MemoryEstimate, MemoryEstimateError> {
        if request.output != ProductSpec::raster(RasterFormat::Rgba8PremultipliedEncoded) {
            return Err(MemoryEstimateError::UnsupportedProduct);
        }
        let contract = (self.parse_contract)(&request.parameters)
            .map_err(|_| MemoryEstimateError::InvalidParameters)?;
        contract
            .validate_output_region(request.output_region)
            .map_err(|_| MemoryEstimateError::InvalidParameters)?;
        let destination_bytes = request
            .output_region
            .size()
            .checked_area()
            .map_err(|_| MemoryEstimateError::Overflow)?
            .checked_mul(4)
            .ok_or(MemoryEstimateError::Overflow)?;
        let horizontal = lanczos_coefficients::scratch_bytes(
            request.output_region.size().width,
            contract.horizontal,
        )
        .ok_or(MemoryEstimateError::Overflow)?;
        let vertical = lanczos_coefficients::scratch_bytes(
            request.output_region.size().height,
            contract.vertical,
        )
        .ok_or(MemoryEstimateError::Overflow)?;
        let coefficient_bytes =
            horizontal.checked_add(vertical).ok_or(MemoryEstimateError::Overflow)?;
        let row_scratch = request
            .output_region
            .size()
            .width
            .checked_mul(contract.vertical.maximum_taps())
            .and_then(|samples| samples.checked_mul(32))
            .ok_or(MemoryEstimateError::Overflow)?;
        let decoded_row = contract
            .source_demand(request.output_region)
            .map_err(|_| MemoryEstimateError::InvalidParameters)?
            .size()
            .width
            .checked_mul(32)
            .ok_or(MemoryEstimateError::Overflow)?;
        let scratch_bytes = coefficient_bytes
            .checked_add(row_scratch)
            .and_then(|bytes| bytes.checked_add(decoded_row))
            .ok_or(MemoryEstimateError::Overflow)?;
        Ok(MemoryEstimate { destination_bytes, scratch_bytes, ..MemoryEstimate::default() })
    }

    pub(crate) const fn cancellation() -> CancellationContract {
        CancellationContract {
            maximum_poll_interval_samples: MAXIMUM_POLL_INTERVAL_SAMPLES,
            atomic_exact_publication: true,
        }
    }

    pub(crate) fn conformance() -> ConformanceRequirements {
        ConformanceRequirements::new([
            ConformanceProof::IndependentOracle,
            ConformanceProof::TileEquivalence,
            ConformanceProof::EmptyRegions,
            ConformanceProof::VariedStrides,
            ConformanceProof::CancellationPoints,
            ConformanceProof::CrossFrontend,
        ])
    }

    pub(crate) fn analyze(&self, request: &OperationRequest) -> RequestAnalysis {
        let contract = (self.parse_contract)(&request.parameters);
        let memory = self.memory(request);
        let output_samples = request.output_region.size().checked_area().unwrap_or_default();
        let (input_samples, support) = contract.map_or((0, SupportRadius::default()), |contract| {
            let demand = contract.source_demand(request.output_region);
            (
                demand
                    .ok()
                    .and_then(|region| region.size().checked_area().ok())
                    .unwrap_or_default(),
                SupportRadius {
                    x: contract.horizontal.support_radius(),
                    y: contract.vertical.support_radius(),
                },
            )
        });
        RequestAnalysis {
            valid: memory.is_ok() && request.quality == QualityTier::Exact,
            required_capabilities: CapabilitySet::default(),
            locality: Locality::Transform,
            support,
            cost: CostEstimate {
                input_samples,
                output_samples,
                work_units: input_samples.saturating_mul(8),
            },
            memory: memory.unwrap_or_default(),
            interactive_quality_available: false,
            diagnostics: Box::default(),
        }
    }

    pub(crate) fn quality(quality: QualityTier) -> bool {
        quality == QualityTier::Exact
    }

    pub(crate) fn execute(
        &self,
        request: &OperationRequest,
        inputs: &[OperationInput<'_>],
        outputs: &mut [OperationOutput<'_>],
        budget: &ExecutionBudget,
    ) -> Result<(), OperationExecutionError> {
        if inputs.len() != 1 || outputs.len() != 1 {
            return Err(OperationExecutionError::MissingProduct);
        }
        let memory = self.memory(request).map_err(|_| OperationExecutionError::InvalidProduct)?;
        if memory.scratch_bytes > budget.scratch_bytes {
            return Err(OperationExecutionError::BudgetExceeded);
        }
        let contract = (self.parse_contract)(&request.parameters)
            .map_err(|_| OperationExecutionError::InvalidProduct)?;
        lanczos_cpu::execute(
            request,
            &inputs[0],
            &mut outputs[0],
            contract,
            budget,
            &self.coefficients,
            &self.colors,
        )
    }
}

impl PartialEq for LanczosImplementation {
    fn eq(&self, other: &Self) -> bool {
        self.descriptor == other.descriptor && self.source_port == other.source_port
    }
}

impl Eq for LanczosImplementation {}

pub(crate) fn identity(
    id: &str,
    version: u32,
) -> Result<OperationIdentity, OperationDefinitionError> {
    Ok(OperationIdentity::new(SemanticOperationId::new(id)?, SemanticVersion::new(version)?))
}

pub(crate) fn ports() -> Result<Box<[PortDescriptor]>, OperationDefinitionError> {
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

pub(crate) fn resize_parameters() -> Result<Vec<ParameterDescriptor>, OperationDefinitionError> {
    Ok(vec![
        dimension_parameter("source_width")?,
        dimension_parameter("source_height")?,
        dimension_parameter("destination_width")?,
        dimension_parameter("destination_height")?,
        edge_parameter()?,
        working_space_parameter()?,
    ])
}

pub(crate) fn view_parameters() -> Result<Vec<ParameterDescriptor>, OperationDefinitionError> {
    let mut parameters = resize_parameters()?;
    parameters.insert(4, scalar_parameter("source_center_x", 0.0, None)?);
    parameters.insert(5, scalar_parameter("source_center_y", 0.0, None)?);
    parameters
        .insert(6, scalar_parameter("source_step_x", 1.0, Some((f64::MIN_POSITIVE, f64::MAX)))?);
    parameters
        .insert(7, scalar_parameter("source_step_y", 1.0, Some((f64::MIN_POSITIVE, f64::MAX)))?);
    Ok(parameters)
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

fn scalar_parameter(
    id: &str,
    default: f64,
    hard_range: Option<(f64, f64)>,
) -> Result<ParameterDescriptor, OperationDefinitionError> {
    Ok(ParameterDescriptor {
        id: ParameterId::new(id)?,
        parameter_type: ParameterType::Scalar,
        unit: Unit::Pixels,
        default: ParameterValue::Scalar(ferrastra_core::FiniteScalar::new(default)?),
        hard_range: hard_range
            .map(|(minimum, maximum)| {
                ParameterRange::scalar(
                    ferrastra_core::FiniteScalar::new(minimum)?,
                    ferrastra_core::FiniteScalar::new(maximum)?,
                )
            })
            .transpose()?,
        recommended_range: None,
        enum_values: Box::default(),
    })
}

fn edge_parameter() -> Result<ParameterDescriptor, OperationDefinitionError> {
    enum_parameter("edge_mode", "clamp", &["clamp", "transparent", "reflect", "wrap"])
}

fn working_space_parameter() -> Result<ParameterDescriptor, OperationDefinitionError> {
    enum_parameter("working_space", "srgb_linear", &["srgb_encoded", "srgb_linear"])
}

fn enum_parameter(
    id: &str,
    default: &str,
    values: &[&str],
) -> Result<ParameterDescriptor, OperationDefinitionError> {
    Ok(ParameterDescriptor {
        id: ParameterId::new(id)?,
        parameter_type: ParameterType::Enum,
        unit: Unit::Unitless,
        default: ParameterValue::Enum(ParameterId::new(default)?),
        hard_range: None,
        recommended_range: None,
        enum_values: values
            .iter()
            .map(|value| ParameterId::new(*value))
            .collect::<Result<Vec<_>, _>>()?
            .into_boxed_slice(),
    })
}

pub(crate) fn computation_descriptor() -> ComputationDescriptor {
    ComputationDescriptor {
        formats: Box::new([ProductFormat::Raster(RasterFormat::Rgba8PremultipliedEncoded)]),
        alpha_modes: Box::new([AlphaMode::Premultiplied]),
        working_spaces: Box::new([WorkingSpace::SrgbEncoded, WorkingSpace::SrgbLinear]),
        edge_modes: Box::new([
            EdgeMode::Clamp,
            EdgeMode::Transparent,
            EdgeMode::Reflect,
            EdgeMode::Wrap,
        ]),
        quality_tiers: Box::new([QualityTier::Exact]),
        locality: Locality::Transform,
        support: SupportRadius { x: MAX_DIMENSION as u64, y: MAX_DIMENSION as u64 },
        required_capabilities: CapabilitySet::default(),
        deterministic: true,
        tile_equivalent: true,
    }
}
