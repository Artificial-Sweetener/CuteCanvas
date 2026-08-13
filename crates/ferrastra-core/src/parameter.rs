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

//! Responsibility: Define canonical typed parameter values, identifiers, units, and scalar ranges.
//!
//! Does not own: graph parameter binding, authoring controls, serialization, or operation defaults.

use std::fmt;
use std::hash::{Hash, Hasher};
use std::str::FromStr;

/// Error returned when a typed value is not canonical.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ValueError {
    /// A scalar value was NaN or infinite.
    NonFiniteScalar,
    /// A parameter or enum identifier was empty or malformed.
    InvalidIdentifier,
    /// A range placed its maximum below its minimum.
    ReversedRange,
    /// A value did not match the declared parameter type.
    TypeMismatch,
    /// A scalar value fell outside a declared inclusive range.
    OutsideRange,
}

impl fmt::Display for ValueError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let message = match self {
            Self::NonFiniteScalar => "parameter scalar must be finite",
            Self::InvalidIdentifier => "parameter identifier is not canonical",
            Self::ReversedRange => "parameter range maximum is below its minimum",
            Self::TypeMismatch => "parameter value does not match its declared type",
            Self::OutsideRange => "parameter value is outside its declared range",
        };
        formatter.write_str(message)
    }
}

impl std::error::Error for ValueError {}

/// Finite canonical scalar that normalizes negative zero.
#[derive(Clone, Copy, Debug, PartialOrd)]
pub struct FiniteScalar(f64);

impl FiniteScalar {
    /// Construct a finite scalar and normalize both zero representations.
    ///
    /// # Errors
    ///
    /// Returns [`ValueError::NonFiniteScalar`] when `value` is NaN or infinite.
    pub fn new(value: f64) -> Result<Self, ValueError> {
        if !value.is_finite() {
            return Err(ValueError::NonFiniteScalar);
        }
        Ok(Self(if value == 0.0 { 0.0 } else { value }))
    }

    /// Return the finite numerical value.
    #[must_use]
    pub const fn get(self) -> f64 {
        self.0
    }
}

impl Eq for FiniteScalar {}

impl PartialEq for FiniteScalar {
    fn eq(&self, other: &Self) -> bool {
        self.0.to_bits() == other.0.to_bits()
    }
}

impl Hash for FiniteScalar {
    fn hash<H: Hasher>(&self, state: &mut H) {
        self.0.to_bits().hash(state);
    }
}

/// Stable lowercase identifier for one operation parameter.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct ParameterId(Box<str>);

impl ParameterId {
    /// Validate and construct a parameter identifier.
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

    /// Return the canonical identifier text.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for ParameterId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.as_str())
    }
}

impl FromStr for ParameterId {
    type Err = ValueError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Self::new(value)
    }
}

/// Semantic unit attached to a numerical parameter.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum Unit {
    /// Dimensionless scalar.
    Unitless,
    /// Pixel distance in the operation's declared coordinate space.
    Pixels,
    /// Angular degrees.
    Degrees,
    /// Normalized ratio in the inclusive range zero through one.
    Ratio,
    /// Percentage expressed on a zero through one numerical scale.
    Percent,
}

/// Runtime type of a normalized parameter value.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum ParameterType {
    /// Boolean value.
    Boolean,
    /// Signed integer value.
    Integer,
    /// Finite floating-point scalar.
    Scalar,
    /// UTF-8 text.
    Text,
    /// Stable enum-case identifier.
    Enum,
}

/// Canonical typed operation parameter value.
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub enum ParameterValue {
    /// Boolean value.
    Boolean(bool),
    /// Signed integer value.
    Integer(i64),
    /// Finite scalar value.
    Scalar(FiniteScalar),
    /// UTF-8 text.
    Text(Box<str>),
    /// Stable enum-case identifier.
    Enum(ParameterId),
}

impl ParameterValue {
    /// Return the runtime type of this value.
    #[must_use]
    pub const fn parameter_type(&self) -> ParameterType {
        match self {
            Self::Boolean(_) => ParameterType::Boolean,
            Self::Integer(_) => ParameterType::Integer,
            Self::Scalar(_) => ParameterType::Scalar,
            Self::Text(_) => ParameterType::Text,
            Self::Enum(_) => ParameterType::Enum,
        }
    }
}

/// Inclusive numerical range matching one numerical parameter type.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum ParameterRange {
    /// Signed integer range.
    Integer {
        /// Inclusive minimum.
        minimum: i64,
        /// Inclusive maximum.
        maximum: i64,
    },
    /// Finite scalar range.
    Scalar {
        /// Inclusive minimum.
        minimum: FiniteScalar,
        /// Inclusive maximum.
        maximum: FiniteScalar,
    },
}

impl ParameterRange {
    /// Construct an ordered inclusive integer range.
    ///
    /// # Errors
    ///
    /// Returns [`ValueError::ReversedRange`] when `maximum` is below `minimum`.
    pub const fn integer(minimum: i64, maximum: i64) -> Result<Self, ValueError> {
        if maximum < minimum {
            return Err(ValueError::ReversedRange);
        }
        Ok(Self::Integer { minimum, maximum })
    }

    /// Construct an ordered inclusive finite scalar range.
    ///
    /// # Errors
    ///
    /// Returns [`ValueError::ReversedRange`] when `maximum` is below `minimum`.
    pub fn scalar(minimum: FiniteScalar, maximum: FiniteScalar) -> Result<Self, ValueError> {
        if maximum.get() < minimum.get() {
            return Err(ValueError::ReversedRange);
        }
        Ok(Self::Scalar { minimum, maximum })
    }

    /// Return the numerical parameter type accepted by this range.
    #[must_use]
    pub const fn parameter_type(self) -> ParameterType {
        match self {
            Self::Integer { .. } => ParameterType::Integer,
            Self::Scalar { .. } => ParameterType::Scalar,
        }
    }

    /// Validate a parameter value against its type and numerical range.
    ///
    /// # Errors
    ///
    /// Returns [`ValueError::TypeMismatch`] for a non-matching value or
    /// [`ValueError::OutsideRange`] when the numerical value is outside this range.
    pub fn validate(self, value: &ParameterValue) -> Result<(), ValueError> {
        match (self, value) {
            (Self::Integer { minimum, maximum }, ParameterValue::Integer(value)) => {
                if *value < minimum || *value > maximum {
                    return Err(ValueError::OutsideRange);
                }
            }
            (Self::Scalar { minimum, maximum }, ParameterValue::Scalar(value)) => {
                if value.get() < minimum.get() || value.get() > maximum.get() {
                    return Err(ValueError::OutsideRange);
                }
            }
            _ => return Err(ValueError::TypeMismatch),
        }
        Ok(())
    }

    /// Return whether `other` has the same type and is fully contained by this range.
    #[must_use]
    pub const fn contains(self, other: Self) -> bool {
        match (self, other) {
            (
                Self::Integer { minimum, maximum },
                Self::Integer { minimum: other_minimum, maximum: other_maximum },
            ) => other_minimum >= minimum && other_maximum <= maximum,
            (
                Self::Scalar { minimum, maximum },
                Self::Scalar { minimum: other_minimum, maximum: other_maximum },
            ) => other_minimum.get() >= minimum.get() && other_maximum.get() <= maximum.get(),
            _ => false,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn finite_scalars_normalize_zero_and_reject_non_finite_values() {
        let negative_zero = FiniteScalar::new(-0.0)
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"));
        let positive_zero = FiniteScalar::new(0.0)
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"));

        assert_eq!(negative_zero, positive_zero);
        assert_eq!(FiniteScalar::new(f64::NAN), Err(ValueError::NonFiniteScalar));
        assert_eq!(FiniteScalar::new(f64::INFINITY), Err(ValueError::NonFiniteScalar));
    }

    #[test]
    fn parameter_identifiers_and_ranges_are_explicit() {
        let identifier = ParameterId::new("working_radius")
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"));
        let range = ParameterRange::scalar(
            FiniteScalar::new(0.0)
                .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}")),
            FiniteScalar::new(10.0)
                .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}")),
        )
        .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"));

        assert_eq!(identifier.as_str(), "working_radius");
        assert_eq!(ParameterId::new("WorkingRadius"), Err(ValueError::InvalidIdentifier));
        assert_eq!(
            range.validate(&ParameterValue::Scalar(
                FiniteScalar::new(4.0)
                    .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"))
            )),
            Ok(())
        );
        assert_eq!(
            range.validate(&ParameterValue::Scalar(
                FiniteScalar::new(11.0)
                    .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"))
            )),
            Err(ValueError::OutsideRange)
        );
        assert_eq!(range.validate(&ParameterValue::Boolean(true)), Err(ValueError::TypeMismatch));
        let integer_range = ParameterRange::integer(-4, 8)
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"));
        assert_eq!(integer_range.validate(&ParameterValue::Integer(8)), Ok(()));
        assert_eq!(
            integer_range.validate(&ParameterValue::Integer(9)),
            Err(ValueError::OutsideRange)
        );
    }
}
