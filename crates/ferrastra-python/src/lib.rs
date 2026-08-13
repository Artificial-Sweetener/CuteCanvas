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

//! Responsibility: Register Ferrastra's typed private native Python boundary.
//!
//! Does not own: kernels, graph semantics, stores, scheduling, caches, application adapters,
//! or public Python documentation policy.

mod budget;
mod buffer;
mod engine;
mod errors;
mod graph;
mod region;
mod requirements;
mod result;

use pyo3::prelude::*;

use budget::{PyCancellationToken, PyEvaluationBudget};
use engine::{PyCompiledGraph, PyEngine};
use graph::{PyGraph, PyGraphBuilder};
use region::PyRegion;
use requirements::PyEvaluationRequirements;
use result::{PyCoverageResult, PyRasterResult};

/// Return the Cargo package version embedded in the native extension.
#[pyfunction]
#[must_use]
fn package_version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

/// Register Ferrastra's private native packaging boundary.
#[pymodule]
fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    errors::register(module)?;
    module.add_class::<PyCancellationToken>()?;
    module.add_class::<PyEvaluationBudget>()?;
    module.add_class::<PyEvaluationRequirements>()?;
    module.add_class::<PyGraph>()?;
    module.add_class::<PyGraphBuilder>()?;
    module.add_class::<PyCompiledGraph>()?;
    module.add_class::<PyRegion>()?;
    module.add_class::<PyEngine>()?;
    module.add_class::<PyRasterResult>()?;
    module.add_class::<PyCoverageResult>()?;
    module.add_function(wrap_pyfunction!(package_version, module)?)?;
    module.add(
        "__all__",
        [
            "BufferError",
            "CancellationToken",
            "CompiledGraph",
            "CoverageResult",
            "Engine",
            "EvaluationBudget",
            "EvaluationError",
            "EvaluationRequirements",
            "FerrastraError",
            "Graph",
            "GraphBuilder",
            "GraphError",
            "RasterResult",
            "Region",
            "package_version",
        ],
    )?;
    Ok(())
}
