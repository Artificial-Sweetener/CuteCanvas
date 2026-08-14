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

//! Responsibility: Define Ferrastra's stable, framework-neutral value and operation contracts.
//!
//! Does not own: graph mutation, product storage, evaluation scheduling, numerical kernels,
//! language behavior, Python bindings, or presentation policy.

mod analysis;
mod descriptor;
mod diagnostic;
mod execution;
mod geometry;
mod identity;
mod invocation;
mod operation;
mod parameter;
mod product;
mod report;
mod view;

pub use analysis::{
    Capability, CapabilitySet, CostEstimate, Locality, RequestAnalysis, SupportRadius,
};
pub use descriptor::{
    AuthoringDescriptor, ComputationDescriptor, DescriptorError, ExposureClass, OperationCategory,
    OperationDescriptor, ParameterDescriptor, PortDescriptor, PortDirection, PortId,
};
pub use diagnostic::{
    Diagnostic, DiagnosticCode, DiagnosticError, DiagnosticSeverity, DiagnosticTarget,
};
pub use execution::{
    CancellationError, CancellationToken, ExecutionBudget, MemoryEstimate, MemoryEstimateError,
};
pub use geometry::{
    AffineTransform, FloatPoint, FloatRect, GeometryError, IntPoint, IntRect, IntSize,
    SAMPLE_CENTER_OFFSET, ScaleFootprint, TransformError,
};
pub use identity::{
    ContentId, IdentityError, OperationIdentity, SemanticOperationId, SemanticVersion,
};
pub use invocation::{OperationDamageRequest, OperationParameters, OperationRequest};
pub use operation::{
    CancellationContract, ConformanceProof, ConformanceRequirements, InputDemand, Operation,
    OperationContractError, OperationExecutionError, OperationInput, OperationKernel,
    OperationOutput,
};
pub use parameter::{
    FiniteScalar, ParameterId, ParameterRange, ParameterType, ParameterValue, Unit, ValueError,
};
pub use product::{
    AlphaMode, ChannelOrder, ComponentRepresentation, CoverageFormat, EdgeMode, ProductFormat,
    ProductKind, ProductSpec, ProductSpecError, QualityTier, RasterFormat, TransferFunction,
    WorkingSpace,
};
pub use report::{EvaluationCounters, EvaluationOutcome, EvaluationReport};
pub use view::{ProductView, ProductViewError, ProductViewMut};
