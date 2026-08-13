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

//! Responsibility: Define actionable terminal failures for bounded graph evaluation.
//!
//! Does not own: diagnostic presentation, retry policy, host admission, or partial publication.

use std::fmt;

use ferrastra_core::{
    GeometryError, MemoryEstimateError, OperationContractError, OperationExecutionError,
    ProductViewError,
};
use ferrastra_store::{ImageProductError, RasterProductError};

/// Error returned without publishing a partial exact evaluation result.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EvaluationError {
    /// The requested named graph output does not exist.
    UnknownOutput,
    /// A compiled plan references an unavailable operation contract or kernel.
    MissingOperation,
    /// A source revision is absent from the supplied source provider.
    MissingSource,
    /// The current executable slice does not accept a declared external graph input.
    GraphInputUnsupported,
    /// The current executable slice requires constant operation parameters.
    GraphParameterUnsupported,
    /// One node received incompatible output-port or product demands.
    ConflictingDemand,
    /// Regional demand is outside the retained source bounds.
    SourceRegionUnavailable,
    /// Checked geometry failed during planning.
    Geometry(GeometryError),
    /// An operation rejected the request's spatial or parameter contract.
    Planning(OperationContractError),
    /// Memory accounting failed or exceeded the caller-owned limit.
    Memory(MemoryEstimateError),
    /// Exact checked memory accounting exceeds the caller-owned total or scratch limit.
    MemoryLimitExceeded,
    /// Borrowed or owned raster layout was invalid.
    Product,
    /// Numerical operation execution failed.
    Operation(OperationExecutionError),
    /// Cooperative cancellation or deadline expiration ended evaluation.
    Cancelled,
}

impl fmt::Display for EvaluationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::UnknownOutput => formatter.write_str("named graph output is unavailable"),
            Self::MissingOperation => formatter.write_str("compiled operation is unavailable"),
            Self::MissingSource => formatter.write_str("source revision is unavailable"),
            Self::GraphInputUnsupported => {
                formatter.write_str("external graph inputs are unavailable in this runtime slice")
            }
            Self::GraphParameterUnsupported => formatter
                .write_str("exposed graph parameters are unavailable in this runtime slice"),
            Self::ConflictingDemand => {
                formatter.write_str("node received incompatible downstream demands")
            }
            Self::SourceRegionUnavailable => {
                formatter.write_str("requested region is outside source bounds")
            }
            Self::Geometry(error) => error.fmt(formatter),
            Self::Planning(error) => error.fmt(formatter),
            Self::Memory(error) => error.fmt(formatter),
            Self::MemoryLimitExceeded => {
                formatter.write_str("evaluation exceeds its caller-owned memory limit")
            }
            Self::Product => formatter.write_str("runtime raster product layout is invalid"),
            Self::Operation(error) => error.fmt(formatter),
            Self::Cancelled => formatter.write_str("evaluation was cancelled"),
        }
    }
}

impl std::error::Error for EvaluationError {}

impl From<GeometryError> for EvaluationError {
    fn from(error: GeometryError) -> Self {
        Self::Geometry(error)
    }
}

impl From<MemoryEstimateError> for EvaluationError {
    fn from(error: MemoryEstimateError) -> Self {
        Self::Memory(error)
    }
}

impl From<OperationContractError> for EvaluationError {
    fn from(error: OperationContractError) -> Self {
        Self::Planning(error)
    }
}

impl From<OperationExecutionError> for EvaluationError {
    fn from(error: OperationExecutionError) -> Self {
        if error == OperationExecutionError::Cancelled {
            Self::Cancelled
        } else {
            Self::Operation(error)
        }
    }
}

impl From<ProductViewError> for EvaluationError {
    fn from(_: ProductViewError) -> Self {
        Self::Product
    }
}

impl From<RasterProductError> for EvaluationError {
    fn from(_: RasterProductError) -> Self {
        Self::Product
    }
}

impl From<ImageProductError> for EvaluationError {
    fn from(_: ImageProductError) -> Self {
        Self::Product
    }
}
