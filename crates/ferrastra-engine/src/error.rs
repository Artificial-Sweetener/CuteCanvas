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

//! Responsibility: Preserve owned subsystem error causes at the high-level engine boundary.
//!
//! Does not own: subsystem recovery policy, diagnostics rendering, retries, or host admission.

use std::fmt;

use ferrastra_graph::CompileError;
use ferrastra_raster::OperationDefinitionError;
use ferrastra_runtime::{EvaluationError, RegistryError};
use ferrastra_store::{CoverageProductError, RasterProductError, RetentionError};

/// Error returned by a high-level engine workflow with its authoritative subsystem cause.
#[derive(Debug)]
pub enum EngineError {
    /// Built-in operation declaration failed validation.
    OperationDefinition(OperationDefinitionError),
    /// Built-in operation registration failed.
    Registry(RegistryError),
    /// Borrowed raster adoption failed.
    RasterProduct(RasterProductError),
    /// Borrowed coverage adoption failed.
    CoverageProduct(CoverageProductError),
    /// Source retention accounting failed.
    Retention(RetentionError),
    /// Graph compilation failed.
    Compile(CompileError),
    /// Bounded evaluation failed without publication.
    Evaluation(EvaluationError),
}

impl fmt::Display for EngineError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::OperationDefinition(error) => error.fmt(formatter),
            Self::Registry(error) => error.fmt(formatter),
            Self::RasterProduct(error) => error.fmt(formatter),
            Self::CoverageProduct(error) => error.fmt(formatter),
            Self::Retention(error) => error.fmt(formatter),
            Self::Compile(error) => error.fmt(formatter),
            Self::Evaluation(error) => error.fmt(formatter),
        }
    }
}

impl std::error::Error for EngineError {}

impl From<OperationDefinitionError> for EngineError {
    fn from(error: OperationDefinitionError) -> Self {
        Self::OperationDefinition(error)
    }
}

impl From<RegistryError> for EngineError {
    fn from(error: RegistryError) -> Self {
        Self::Registry(error)
    }
}

impl From<RasterProductError> for EngineError {
    fn from(error: RasterProductError) -> Self {
        Self::RasterProduct(error)
    }
}

impl From<CoverageProductError> for EngineError {
    fn from(error: CoverageProductError) -> Self {
        Self::CoverageProduct(error)
    }
}

impl From<RetentionError> for EngineError {
    fn from(error: RetentionError) -> Self {
        Self::Retention(error)
    }
}

impl From<CompileError> for EngineError {
    fn from(error: CompileError) -> Self {
        Self::Compile(error)
    }
}

impl From<EvaluationError> for EngineError {
    fn from(error: EvaluationError) -> Self {
        Self::Evaluation(error)
    }
}
