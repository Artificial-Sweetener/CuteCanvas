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

//! Responsibility: Define the framework-neutral spatial operation execution contract.
//!
//! Does not own: operation metadata, implementations, graph compilation, runtime dispatch, or bindings.

use std::collections::BTreeSet;
use std::num::NonZeroU64;

use crate::{
    ExecutionBudget, GeometryError, IntRect, MemoryEstimate, MemoryEstimateError,
    OperationDamageRequest, OperationDescriptor, OperationRequest, PortId, ProductView,
    ProductViewMut, QualityTier, RequestAnalysis,
};

/// Error returned when an operation cannot produce a valid spatial contract for a request.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OperationContractError {
    /// Checked integer geometry could not represent the requested mapping.
    Geometry(GeometryError),
    /// Invocation parameters are absent, ill-typed, or internally inconsistent.
    InvalidParameters,
    /// The requested output region lies outside the operation's declared output domain.
    OutputRegionUnavailable,
}

impl std::fmt::Display for OperationContractError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Geometry(error) => error.fmt(formatter),
            Self::InvalidParameters => formatter.write_str("operation parameters are invalid"),
            Self::OutputRegionUnavailable => {
                formatter.write_str("requested output region is outside the operation domain")
            }
        }
    }
}

impl std::error::Error for OperationContractError {}

impl From<GeometryError> for OperationContractError {
    fn from(error: GeometryError) -> Self {
        Self::Geometry(error)
    }
}

/// Error returned by a numerical operation without publishing partial exact output.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OperationExecutionError {
    /// Cooperative cancellation was observed.
    Cancelled,
    /// Required input or output product was absent.
    MissingProduct,
    /// A supplied product format, region, or layout violated the operation contract.
    InvalidProduct,
    /// Caller-supplied scratch or execution limits were insufficient.
    BudgetExceeded,
}

impl std::fmt::Display for OperationExecutionError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let message = match self {
            Self::Cancelled => "operation execution was cancelled",
            Self::MissingProduct => "operation execution requires another product",
            Self::InvalidProduct => "operation product violates its declared contract",
            Self::BudgetExceeded => "operation execution budget is insufficient",
        };
        formatter.write_str(message)
    }
}

impl std::error::Error for OperationExecutionError {}

/// Named immutable regional input supplied to one operation invocation.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct OperationInput<'a> {
    /// Declared input port.
    pub port: &'a PortId,
    /// Global half-open region represented by `product`.
    pub region: IntRect,
    /// Immutable borrowed product bytes.
    pub product: ProductView<'a>,
}

/// Named unpublished mutable regional output supplied to one operation invocation.
#[derive(Debug)]
pub struct OperationOutput<'a> {
    /// Declared output port.
    pub port: &'a PortId,
    /// Global half-open region represented by `product`.
    pub region: IntRect,
    /// Exclusive unpublished destination storage.
    pub product: ProductViewMut<'a>,
}

/// Named upstream region required to produce one operation output request.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct InputDemand {
    /// Declared input port.
    pub port: PortId,
    /// Exact global half-open source region required from that port.
    pub region: IntRect,
}

/// Operation-level cancellation and publication contract.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CancellationContract {
    /// Maximum number of output samples processed between cancellation polls.
    pub maximum_poll_interval_samples: NonZeroU64,
    /// Whether incomplete exact products are withheld atomically.
    pub atomic_exact_publication: bool,
}

/// One required proof of an operation's declared behavior.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum ConformanceProof {
    /// Compare the implementation with an independent scalar or fixed canonical oracle.
    IndependentOracle,
    /// Prove that partitioning preserves the exact result.
    TileEquivalence,
    /// Exercise empty output requests.
    EmptyRegions,
    /// Exercise non-default valid source and destination strides.
    VariedStrides,
    /// Exercise cancellation at multiple progress points.
    CancellationPoints,
    /// Prove that every supported frontend normalizes identically.
    CrossFrontend,
}

/// Deterministic set of conformance proofs required by one operation.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct ConformanceRequirements {
    required: BTreeSet<ConformanceProof>,
}

impl ConformanceRequirements {
    /// Construct a requirement set from any sequence of proof kinds.
    #[must_use]
    pub fn new(required: impl IntoIterator<Item = ConformanceProof>) -> Self {
        Self { required: required.into_iter().collect() }
    }

    /// Return whether a proof kind is required.
    #[must_use]
    pub fn contains(&self, proof: ConformanceProof) -> bool {
        self.required.contains(&proof)
    }

    /// Iterate over required proof kinds in deterministic order.
    #[must_use]
    pub fn iter(&self) -> impl ExactSizeIterator<Item = ConformanceProof> + '_ {
        self.required.iter().copied()
    }
}

/// Framework-neutral contract implemented by every executable operation.
pub trait Operation: Send + Sync {
    /// Return the complete authoritative descriptor.
    fn descriptor(&self) -> &OperationDescriptor;

    /// Compute exact upstream regions required for one output request.
    ///
    /// # Errors
    ///
    /// Returns [`GeometryError`] when required source regions are not representable.
    fn backward_demand(
        &self,
        request: &OperationRequest,
    ) -> Result<Box<[InputDemand]>, OperationContractError>;

    /// Compute exact downstream damage caused by a changed input region.
    ///
    /// # Errors
    ///
    /// Returns [`GeometryError`] when the damaged output region is not representable.
    fn forward_damage(
        &self,
        request: &OperationDamageRequest,
    ) -> Result<IntRect, OperationContractError>;

    /// Estimate destination, scratch, retained, and in-flight bytes before execution.
    ///
    /// # Errors
    ///
    /// Returns [`MemoryEstimateError`] when the estimate cannot be represented.
    fn memory(&self, request: &OperationRequest) -> Result<MemoryEstimate, MemoryEstimateError>;

    /// Return the bounded cancellation and publication contract.
    fn cancellation(&self) -> CancellationContract;

    /// Return the conformance proof required for this operation.
    fn conformance(&self) -> ConformanceRequirements;

    /// Produce deterministic request analysis for host admission.
    fn analyze(&self, request: &OperationRequest) -> RequestAnalysis;

    /// Return whether the operation supports the requested quality tier.
    fn quality(&self, quality: QualityTier) -> bool {
        self.descriptor().computation.quality_tiers.contains(&quality)
    }
}

/// Numerical execution contract implemented by pure executable operations.
pub trait OperationKernel: Operation {
    /// Execute one admitted bounded request into unpublished destinations.
    ///
    /// Implementations poll `budget` within their declared cancellation interval. An error leaves
    /// every destination unpublished and unusable as an immutable exact product.
    ///
    /// # Errors
    ///
    /// Returns [`OperationExecutionError`] for cancellation, missing or invalid products, or an
    /// insufficient caller-owned budget.
    fn execute(
        &self,
        request: &OperationRequest,
        inputs: &[OperationInput<'_>],
        outputs: &mut [OperationOutput<'_>],
        budget: &ExecutionBudget,
    ) -> Result<(), OperationExecutionError>;
}
