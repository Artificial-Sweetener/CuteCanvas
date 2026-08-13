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

//! Responsibility: Define complete authoritative operation metadata and its validation contract.
//!
//! Does not own: operation execution traits, implementations, graph compilation, bindings, or authoring UI.

use std::collections::BTreeSet;
use std::fmt;
use std::str::FromStr;

use crate::{
    AlphaMode, CapabilitySet, EdgeMode, Locality, OperationIdentity, ParameterId, ParameterRange,
    ParameterType, ParameterValue, ProductFormat, ProductSpec, QualityTier, SupportRadius, Unit,
    ValueError, WorkingSpace,
};

/// Exposure boundary of an operation entry point.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum ExposureClass {
    /// Available to every supported graph-authoring frontend.
    PublicGraph,
    /// Available only to a trusted host adapter.
    HostOnly,
    /// Available only through a transactional native session.
    SessionOnly,
    /// Internal implementation detail unavailable to external construction.
    Internal,
}

/// Stable operation category used for discovery and contract specialization.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum OperationCategory {
    /// Per-sample operation with aligned demand and damage.
    Point,
    /// Finite-neighborhood area operation.
    Area,
    /// Spatial transform operation.
    Transform,
    /// Multi-input composition operation.
    Composite,
    /// Source-independent generator.
    Generator,
    /// Analysis producing non-raster data.
    Analysis,
    /// Framework-neutral vector computation.
    Vector,
}

/// Stable lowercase identifier for a named operation port.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct PortId(Box<str>);

impl PortId {
    /// Validate and construct a port identifier.
    ///
    /// # Errors
    ///
    /// Returns [`ValueError::InvalidIdentifier`] when the value is not canonical.
    pub fn new(value: impl Into<Box<str>>) -> Result<Self, ValueError> {
        let value = value.into();
        let mut characters = value.bytes();
        let valid = characters.next().is_some_and(|first| first.is_ascii_lowercase())
            && characters.all(|character| {
                character.is_ascii_lowercase() || character.is_ascii_digit() || character == b'_'
            });
        if valid { Ok(Self(value)) } else { Err(ValueError::InvalidIdentifier) }
    }

    /// Return the canonical port identifier.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for PortId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.as_str())
    }
}

impl FromStr for PortId {
    type Err = ValueError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Self::new(value)
    }
}

/// Direction of a typed operation port.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum PortDirection {
    /// Operation input.
    Input,
    /// Operation output.
    Output,
}

/// Typed named operation port.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PortDescriptor {
    /// Stable port identifier.
    pub id: PortId,
    /// Port direction.
    pub direction: PortDirection,
    /// Required product contract.
    pub product: ProductSpec,
    /// Whether an input port must be connected.
    pub required: bool,
}

/// Typed operation parameter contract.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ParameterDescriptor {
    /// Stable parameter identifier.
    pub id: ParameterId,
    /// Accepted runtime type.
    pub parameter_type: ParameterType,
    /// Semantic unit.
    pub unit: Unit,
    /// Normalized default value.
    pub default: ParameterValue,
    /// Inclusive validity range for numerical parameters.
    pub hard_range: Option<ParameterRange>,
    /// Inclusive preferred authoring range.
    pub recommended_range: Option<ParameterRange>,
    /// Allowed cases for enum parameters.
    pub enum_values: Box<[ParameterId]>,
}

impl ParameterDescriptor {
    /// Validate the descriptor's default, ranges, and enum domain.
    ///
    /// # Errors
    ///
    /// Returns [`ValueError`] when the default, ranges, or enum domain contradict the descriptor.
    pub fn validate(&self) -> Result<(), ValueError> {
        self.validate_value(&self.default)?;
        if let Some(range) = self.hard_range {
            if let Some(recommended) = self.recommended_range
                && !range.contains(recommended)
            {
                return Err(ValueError::OutsideRange);
            }
        } else if let Some(recommended) = self.recommended_range
            && recommended.parameter_type() != self.parameter_type
        {
            return Err(ValueError::TypeMismatch);
        }
        if self.parameter_type != ParameterType::Enum && !self.enum_values.is_empty() {
            return Err(ValueError::TypeMismatch);
        }
        Ok(())
    }

    /// Validate one normalized value against this parameter's type, hard range, and enum domain.
    ///
    /// # Errors
    ///
    /// Returns [`ValueError`] when the value violates the declared parameter contract.
    pub fn validate_value(&self, value: &ParameterValue) -> Result<(), ValueError> {
        if value.parameter_type() != self.parameter_type {
            return Err(ValueError::TypeMismatch);
        }
        if let Some(range) = self.hard_range {
            range.validate(value)?;
        }
        if let ParameterValue::Enum(value) = value
            && !self.enum_values.contains(value)
        {
            return Err(ValueError::OutsideRange);
        }
        Ok(())
    }
}

/// Computational metadata that participates in validation and conformance.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ComputationDescriptor {
    /// Supported concrete raster-like formats.
    pub formats: Box<[ProductFormat]>,
    /// Supported alpha representations.
    pub alpha_modes: Box<[AlphaMode]>,
    /// Supported working spaces.
    pub working_spaces: Box<[WorkingSpace]>,
    /// Supported out-of-bounds behaviors.
    pub edge_modes: Box<[EdgeMode]>,
    /// Supported deterministic quality tiers.
    pub quality_tiers: Box<[QualityTier]>,
    /// Spatial locality class.
    pub locality: Locality,
    /// Maximum declared finite support.
    pub support: SupportRadius,
    /// Required capabilities independent of host policy.
    pub required_capabilities: CapabilitySet,
    /// Whether identical normalized inputs always produce identical results.
    pub deterministic: bool,
    /// Whether partitioning a request into tiles preserves the exact contract.
    pub tile_equivalent: bool,
}

/// Human-facing metadata excluded from computational identity.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthoringDescriptor {
    /// Concise operation summary.
    pub summary: Box<str>,
    /// Detailed operation behavior.
    pub details: Box<str>,
    /// Intended use cases.
    pub use_cases: Box<[Box<str>]>,
    /// Important warnings.
    pub warnings: Box<[Box<str>]>,
}

/// Complete authoritative operation catalog entry.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OperationDescriptor {
    /// Stable numerical identity.
    pub identity: OperationIdentity,
    /// External exposure boundary.
    pub exposure: ExposureClass,
    /// Stable category.
    pub category: OperationCategory,
    /// Typed ports.
    pub ports: Box<[PortDescriptor]>,
    /// Typed parameters.
    pub parameters: Box<[ParameterDescriptor]>,
    /// Computational contract.
    pub computation: ComputationDescriptor,
    /// Human-facing metadata excluded from product identity.
    pub authoring: AuthoringDescriptor,
    /// Version of the descriptor serialization shape.
    pub serialization_version: u32,
}

/// Error returned when an operation descriptor contains contradictory or incomplete metadata.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DescriptorError {
    /// Descriptor serialization versions start at one.
    ZeroSerializationVersion,
    /// The operation declared no output port.
    MissingOutput,
    /// Output ports cannot be optional.
    OptionalOutput,
    /// Two ports shared one stable identifier.
    DuplicatePortId,
    /// Two parameters shared one stable identifier.
    DuplicateParameterId,
    /// A parameter descriptor was invalid.
    InvalidParameter(ValueError),
    /// No deterministic quality tier was declared.
    MissingQualityTier,
    /// A port requires a concrete format absent from the computation contract.
    UnsupportedPortFormat,
    /// Raster-like computation metadata omitted alpha, working-space, or edge semantics.
    IncompleteRasterSemantics,
    /// Human-facing summary or details contained no visible text.
    EmptyAuthoringText,
}

impl fmt::Display for DescriptorError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let message = match self {
            Self::ZeroSerializationVersion => "descriptor serialization version must be positive",
            Self::MissingOutput => "operation descriptor requires an output port",
            Self::OptionalOutput => "operation output ports cannot be optional",
            Self::DuplicatePortId => "operation descriptor contains a duplicate port identifier",
            Self::DuplicateParameterId => {
                "operation descriptor contains a duplicate parameter identifier"
            }
            Self::InvalidParameter(error) => return error.fmt(formatter),
            Self::MissingQualityTier => "operation descriptor requires a quality tier",
            Self::UnsupportedPortFormat => {
                "operation port format is absent from the computation contract"
            }
            Self::IncompleteRasterSemantics => {
                "raster computation requires alpha, working-space, and edge semantics"
            }
            Self::EmptyAuthoringText => "operation summary and details must not be empty",
        };
        formatter.write_str(message)
    }
}

impl std::error::Error for DescriptorError {}

impl OperationDescriptor {
    /// Validate the complete computational and authoring descriptor contract.
    ///
    /// # Errors
    ///
    /// Returns [`DescriptorError`] for incomplete, duplicate, or contradictory metadata.
    pub fn validate(&self) -> Result<(), DescriptorError> {
        if self.serialization_version == 0 {
            return Err(DescriptorError::ZeroSerializationVersion);
        }
        if self.authoring.summary.trim().is_empty() || self.authoring.details.trim().is_empty() {
            return Err(DescriptorError::EmptyAuthoringText);
        }
        if self.computation.quality_tiers.is_empty() {
            return Err(DescriptorError::MissingQualityTier);
        }

        let mut port_ids = BTreeSet::new();
        let mut has_output = false;
        for port in &self.ports {
            if !port_ids.insert(&port.id) {
                return Err(DescriptorError::DuplicatePortId);
            }
            if port.direction == PortDirection::Output {
                has_output = true;
                if !port.required {
                    return Err(DescriptorError::OptionalOutput);
                }
            }
            if let Some(format) = port.product.format()
                && !self.computation.formats.contains(&format)
            {
                return Err(DescriptorError::UnsupportedPortFormat);
            }
        }
        if !has_output {
            return Err(DescriptorError::MissingOutput);
        }

        let mut parameter_ids = BTreeSet::new();
        for parameter in &self.parameters {
            if !parameter_ids.insert(&parameter.id) {
                return Err(DescriptorError::DuplicateParameterId);
            }
            parameter.validate().map_err(DescriptorError::InvalidParameter)?;
        }

        if !self.computation.formats.is_empty()
            && (self.computation.alpha_modes.is_empty()
                || self.computation.working_spaces.is_empty()
                || self.computation.edge_modes.is_empty())
        {
            return Err(DescriptorError::IncompleteRasterSemantics);
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::FiniteScalar;

    #[test]
    fn parameter_descriptors_reject_defaults_outside_their_contract() {
        let zero = FiniteScalar::new(0.0)
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"));
        let one = FiniteScalar::new(1.0)
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"));
        let descriptor = ParameterDescriptor {
            id: ParameterId::new("amount")
                .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}")),
            parameter_type: ParameterType::Scalar,
            unit: Unit::Ratio,
            default: ParameterValue::Scalar(one),
            hard_range: Some(
                ParameterRange::scalar(zero, one)
                    .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}")),
            ),
            recommended_range: None,
            enum_values: Box::default(),
        };

        assert_eq!(descriptor.validate(), Ok(()));
    }

    #[test]
    fn port_identifiers_are_canonical_and_typed() {
        let port = PortDescriptor {
            id: PortId::new("source_raster")
                .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}")),
            direction: PortDirection::Input,
            product: ProductSpec::raster(crate::RasterFormat::Rgba8PremultipliedEncoded),
            required: true,
        };

        assert_eq!(port.id.as_str(), "source_raster");
        assert_eq!(PortId::new("source-raster"), Err(ValueError::InvalidIdentifier));
    }

    #[test]
    fn complete_descriptors_reject_duplicate_stable_port_identity() {
        let port = PortDescriptor {
            id: PortId::new("result")
                .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}")),
            direction: PortDirection::Output,
            product: ProductSpec::raster(crate::RasterFormat::Rgba8PremultipliedEncoded),
            required: true,
        };
        let descriptor = OperationDescriptor {
            identity: OperationIdentity::new(
                crate::SemanticOperationId::new("ferrastra.test.identity")
                    .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}")),
                crate::SemanticVersion::new(1)
                    .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}")),
            ),
            exposure: ExposureClass::Internal,
            category: OperationCategory::Point,
            ports: vec![port.clone(), port].into_boxed_slice(),
            parameters: Box::default(),
            computation: ComputationDescriptor {
                formats: Box::new([ProductFormat::Raster(
                    crate::RasterFormat::Rgba8PremultipliedEncoded,
                )]),
                alpha_modes: Box::new([AlphaMode::Premultiplied]),
                working_spaces: Box::new([WorkingSpace::SrgbEncoded]),
                edge_modes: Box::new([EdgeMode::Clamp]),
                quality_tiers: Box::new([QualityTier::Exact]),
                locality: Locality::Local,
                support: SupportRadius::default(),
                required_capabilities: CapabilitySet::default(),
                deterministic: true,
                tile_equivalent: true,
            },
            authoring: AuthoringDescriptor {
                summary: "Identity".into(),
                details: "Produces the requested source samples.".into(),
                use_cases: Box::default(),
                warnings: Box::default(),
            },
            serialization_version: 1,
        };

        assert_eq!(descriptor.validate(), Err(DescriptorError::DuplicatePortId));
    }
}
