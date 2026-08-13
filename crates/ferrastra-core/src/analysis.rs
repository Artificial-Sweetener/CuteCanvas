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

//! Responsibility: Define deterministic capability, locality, support, cost, and request-analysis values.
//!
//! Does not own: host admission decisions, runtime planning, wall-clock prediction, or diagnostics UI.

use std::collections::BTreeSet;

use crate::{Diagnostic, MemoryEstimate, QualityTier};

/// Named execution capability required by an operation or request.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct Capability(Box<str>);

impl Capability {
    /// Construct a capability from a non-empty stable identifier.
    #[must_use]
    pub fn new(value: impl Into<Box<str>>) -> Option<Self> {
        let value = value.into();
        (!value.trim().is_empty()).then_some(Self(value))
    }

    /// Return the capability identifier.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// Deterministically ordered set of capabilities.
pub type CapabilitySet = BTreeSet<Capability>;

/// Spatial locality class of an operation request.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum Locality {
    /// Each output sample depends only on its aligned input sample.
    Local,
    /// Each output region depends on a finite expanded input region.
    BoundedLocal,
    /// Input demand follows a spatial transform.
    Transform,
    /// The operation produces content without a spatial input.
    Generator,
    /// The operation combines multiple spatial inputs.
    Composite,
    /// The request depends on the complete declared domain.
    Global,
}

/// Maximum finite support around a requested sample, in source pixels.
#[derive(Clone, Copy, Debug, Default, Eq, Hash, PartialEq)]
pub struct SupportRadius {
    /// Horizontal support radius.
    pub x: u64,
    /// Vertical support radius.
    pub y: u64,
}

/// Deterministic relative operation-cost estimate.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct CostEstimate {
    /// Estimated input samples inspected.
    pub input_samples: u64,
    /// Estimated output samples produced.
    pub output_samples: u64,
    /// Estimated scalar-equivalent arithmetic work units.
    pub work_units: u64,
}

impl CostEstimate {
    /// Return the checked aggregate work measure.
    #[must_use]
    pub fn checked_total(self) -> Option<u64> {
        self.input_samples.checked_add(self.output_samples)?.checked_add(self.work_units)
    }
}

/// Deterministic request analysis used by a host admission policy.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RequestAnalysis {
    /// Whether the graph and request are valid before host policy.
    pub valid: bool,
    /// Required execution capabilities.
    pub required_capabilities: CapabilitySet,
    /// Operation locality class.
    pub locality: Locality,
    /// Maximum finite source support.
    pub support: SupportRadius,
    /// Relative cost estimate.
    pub cost: CostEstimate,
    /// Explicit memory estimate.
    pub memory: MemoryEstimate,
    /// Whether a declared interactive tier is available.
    pub interactive_quality_available: bool,
    /// Structured validation and cost diagnostics.
    pub diagnostics: Box<[Diagnostic]>,
}

impl RequestAnalysis {
    /// Return whether the request is valid, supported, and fits the supplied memory limits.
    #[must_use]
    pub fn is_admissible(
        &self,
        available_capabilities: &CapabilitySet,
        total_memory_limit: u64,
        scratch_limit: u64,
        quality: QualityTier,
    ) -> bool {
        self.valid
            && self.required_capabilities.is_subset(available_capabilities)
            && self.memory.fits(total_memory_limit, scratch_limit).unwrap_or(false)
            && (quality != QualityTier::Interactive || self.interactive_quality_available)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn request_analysis_keeps_host_admission_explicit() {
        let capability =
            Capability::new("cpu.scalar").unwrap_or_else(|| unreachable!("valid fixture rejected"));
        let required_capabilities = CapabilitySet::from([capability.clone()]);
        let analysis = RequestAnalysis {
            valid: true,
            required_capabilities,
            locality: Locality::BoundedLocal,
            support: SupportRadius { x: 3, y: 3 },
            cost: CostEstimate { input_samples: 16, output_samples: 4, work_units: 80 },
            memory: MemoryEstimate {
                destination_bytes: 64,
                scratch_bytes: 32,
                retained_bytes: 0,
                in_flight_bytes: 0,
            },
            interactive_quality_available: false,
            diagnostics: Box::default(),
        };

        assert!(analysis.is_admissible(
            &CapabilitySet::from([capability]),
            96,
            32,
            QualityTier::Exact
        ));
        assert!(!analysis.is_admissible(&CapabilitySet::new(), 96, 32, QualityTier::Exact));
        assert!(
            !analysis.is_admissible(
                &CapabilitySet::from([Capability::new("cpu.scalar")
                    .unwrap_or_else(|| unreachable!("valid fixture rejected"))]),
                96,
                32,
                QualityTier::Interactive
            )
        );
    }
}
