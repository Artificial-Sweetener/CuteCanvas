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

//! Responsibility: Expose coherent Python source retention, compilation, and evaluation workflows.
//!
//! Does not own: algorithms, graph semantics, storage implementation, or Python buffer parsing.

use ferrastra_core::{CoverageFormat, IntSize, ProductFormat, QualityTier, RasterFormat};
use ferrastra_engine::{CompiledPlan, Engine};
use pyo3::prelude::*;

use crate::budget::PyEvaluationBudget;
use crate::buffer::{canonical_coverage8, canonical_rgba8};
use crate::errors;
use crate::graph::{PyGraph, graph_name};
use crate::region::PyRegion;
use crate::requirements::PyEvaluationRequirements;
use crate::result::{PyCoverageResult, PyRasterResult};

/// Immutable Python handle to one validated minimal execution plan.
#[pyclass(name = "CompiledGraph", module = "ferrastra._native", frozen, skip_from_py_object)]
#[derive(Clone)]
pub(crate) struct PyCompiledGraph {
    inner: CompiledPlan,
}

#[pymethods]
impl PyCompiledGraph {
    /// Return the normalized graph identity captured by compilation.
    #[getter]
    fn graph_content_id(&self) -> String {
        self.inner.graph_content_id().to_string()
    }
}

/// Python assembly for native source retention, graph compilation, and evaluation.
#[pyclass(name = "Engine", module = "ferrastra._native")]
pub(crate) struct PyEngine {
    inner: Engine,
}

#[pymethods]
impl PyEngine {
    /// Construct an engine with the built-in operation catalog.
    #[new]
    fn new() -> PyResult<Self> {
        Engine::new().map(|inner| Self { inner }).map_err(|error| errors::engine(&error))
    }

    /// Copy and retain one strided premultiplied encoded RGBA8 raster.
    #[pyo3(signature = (data, width, height, *, stride_bytes = None))]
    fn add_rgba8(
        &mut self,
        py: Python<'_>,
        data: &Bound<'_, PyAny>,
        width: u64,
        height: u64,
        stride_bytes: Option<usize>,
    ) -> PyResult<String> {
        let tight_stride = usize::try_from(width)
            .ok()
            .and_then(|value| value.checked_mul(4))
            .ok_or_else(|| errors::buffer("raster row byte count overflowed"))?;
        let stride_bytes = stride_bytes.unwrap_or(tight_stride);
        let bytes = canonical_rgba8(py, data, width, height, stride_bytes)?;
        self.inner
            .add_raster_owned(
                bytes,
                IntSize { width, height },
                RasterFormat::Rgba8PremultipliedEncoded,
            )
            .map(|revision| revision.to_string())
            .map_err(|error| errors::engine(&error))
    }

    /// Copy and retain one strided scalar Coverage8 field.
    #[pyo3(signature = (data, width, height, *, stride_bytes = None))]
    fn add_coverage8(
        &mut self,
        py: Python<'_>,
        data: &Bound<'_, PyAny>,
        width: u64,
        height: u64,
        stride_bytes: Option<usize>,
    ) -> PyResult<String> {
        let tight_stride = usize::try_from(width)
            .map_err(|_| errors::buffer("coverage row byte count overflowed"))?;
        let stride_bytes = stride_bytes.unwrap_or(tight_stride);
        let bytes = canonical_coverage8(py, data, width, height, stride_bytes)?;
        self.inner
            .add_coverage_owned(bytes, IntSize { width, height }, CoverageFormat::Coverage8)
            .map(|revision| revision.to_string())
            .map_err(|error| errors::engine(&error))
    }

    /// Validate and compile one immutable graph against this engine's catalog.
    #[expect(
        clippy::needless_pass_by_value,
        reason = "PyO3 extracts the class handle at the FFI boundary"
    )]
    fn compile(&self, graph: PyRef<'_, PyGraph>) -> PyResult<PyCompiledGraph> {
        self.inner
            .compile(graph.inner())
            .map(|inner| PyCompiledGraph { inner })
            .map_err(|error| errors::compile(&error))
    }

    /// Plan the minimum total and scratch budgets for one exact regional evaluation.
    #[pyo3(signature = (compiled, output_name, region))]
    #[expect(
        clippy::needless_pass_by_value,
        reason = "PyO3 extracts class handles at the FFI boundary"
    )]
    fn requirements(
        &self,
        compiled: PyRef<'_, PyCompiledGraph>,
        output_name: &str,
        region: PyRef<'_, PyRegion>,
    ) -> PyResult<PyEvaluationRequirements> {
        let output_name = graph_name(output_name)?;
        self.inner
            .evaluation_requirements(
                &compiled.inner,
                &output_name,
                region.inner(),
                QualityTier::Exact,
            )
            .map(PyEvaluationRequirements::new)
            .map_err(|error| errors::evaluation(&error))
    }

    /// Evaluate and atomically publish one exact regional image result.
    #[pyo3(signature = (compiled, output_name, region, budget))]
    #[expect(
        clippy::needless_pass_by_value,
        reason = "PyO3 extracts class handles at the FFI boundary"
    )]
    fn evaluate(
        &self,
        py: Python<'_>,
        compiled: PyRef<'_, PyCompiledGraph>,
        output_name: &str,
        region: PyRef<'_, PyRegion>,
        budget: PyRef<'_, PyEvaluationBudget>,
    ) -> PyResult<Py<PyAny>> {
        let output_name = graph_name(output_name)?;
        let output_region = region.inner();
        let compiled = compiled.inner.clone();
        let budget = budget.inner();
        let result = py.detach(|| {
            self.inner
                .evaluate(&compiled, &output_name, output_region, QualityTier::Exact, &budget)
                .map_err(|error| errors::evaluation(&error))
        })?;
        match result.product.format() {
            ProductFormat::Raster(_) => Py::new(py, PyRasterResult::new(result)).map(Py::into_any),
            ProductFormat::Coverage(_) => {
                Py::new(py, PyCoverageResult::new(result)).map(Py::into_any)
            }
        }
    }
}
