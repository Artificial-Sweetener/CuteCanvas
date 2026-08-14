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

//! Responsibility: Carry normalized operation parameters into spatial planning and execution.
//!
//! Does not own: parameter schemas, graph bindings, validation diagnostics, or host admission.

use std::collections::BTreeMap;

use crate::{IntRect, ParameterId, ParameterValue, PortId, ProductSpec, QualityTier};

/// Immutable normalized constant values for one operation invocation.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct OperationParameters {
    values: BTreeMap<ParameterId, ParameterValue>,
}

impl OperationParameters {
    /// Adopt a deterministically ordered set of already validated parameter values.
    #[must_use]
    pub const fn new(values: BTreeMap<ParameterId, ParameterValue>) -> Self {
        Self { values }
    }

    /// Return a normalized value by its stable parameter identity.
    #[must_use]
    pub fn get(&self, parameter: &ParameterId) -> Option<&ParameterValue> {
        self.values.get(parameter)
    }

    /// Return a normalized value by canonical parameter text without allocating an identifier.
    #[must_use]
    pub fn get_named(&self, parameter: &str) -> Option<&ParameterValue> {
        self.values
            .iter()
            .find_map(|(identity, value)| (identity.as_str() == parameter).then_some(value))
    }

    /// Return the number of bound values, including descriptor defaults.
    #[must_use]
    pub fn len(&self) -> usize {
        self.values.len()
    }

    /// Return whether no invocation parameter values are present.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.values.is_empty()
    }
}

/// Typed spatial request supplied consistently to planning, analysis, and execution.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OperationRequest {
    /// Requested output region.
    pub output_region: IntRect,
    /// Requested output product.
    pub output: ProductSpec,
    /// Requested deterministic quality tier.
    pub quality: QualityTier,
    /// Descriptor-complete normalized invocation parameters.
    pub parameters: OperationParameters,
}

/// Typed input change supplied to one operation's forward-damage contract.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OperationDamageRequest {
    /// Input port whose upstream product changed.
    pub input: PortId,
    /// Changed half-open region in the input product's coordinate space.
    pub input_damage: IntRect,
    /// Descriptor-complete normalized invocation parameters.
    pub parameters: OperationParameters,
}
