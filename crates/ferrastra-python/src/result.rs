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

//! Responsibility: Expose immutable evaluated raster and coverage products to Python.
//!
//! Does not own: evaluation, product publication, tracing policy, or presentation conversion.

use ferrastra_core::{CoverageFormat, ProductFormat, RasterFormat};
use ferrastra_engine::EvaluationResult;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

use crate::errors;

/// Immutable Python handle to one atomically published raster evaluation result.
#[pyclass(name = "RasterResult", module = "ferrastra._native", frozen)]
pub(crate) struct PyRasterResult {
    inner: EvaluationResult,
}

#[pymethods]
impl PyRasterResult {
    /// Return tightly packed immutable pixels as Python bytes.
    #[getter]
    fn pixels<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyBytes>> {
        product_pixels(&self.inner, py)
    }

    /// Return the raster width in samples.
    #[getter]
    fn width(&self) -> u64 {
        self.inner.product.size().width
    }

    /// Return the raster height in samples.
    #[getter]
    fn height(&self) -> u64 {
        self.inner.product.size().height
    }

    /// Return the tightly packed byte stride.
    #[getter]
    fn stride_bytes(&self) -> usize {
        self.inner.product.stride_bytes()
    }

    /// Return the canonical raster format name.
    #[getter]
    fn format(&self) -> &'static str {
        match self.inner.product.format() {
            ProductFormat::Raster(RasterFormat::Rgba8PremultipliedEncoded) => {
                "rgba8-premultiplied-encoded"
            }
            ProductFormat::Raster(RasterFormat::Rgba16PremultipliedLinear) => {
                "rgba16-premultiplied-linear"
            }
            ProductFormat::Raster(RasterFormat::Rgba32FloatPremultipliedLinear) => {
                "rgba32float-premultiplied-linear"
            }
            ProductFormat::Coverage(_) => unreachable!("coverage product wrapped as raster"),
        }
    }

    /// Return the deterministic semantic product identity.
    #[getter]
    fn product_id(&self) -> PyResult<String> {
        self.inner
            .report
            .product_id()
            .map(|identity| identity.to_string())
            .ok_or_else(|| errors::contract("published result has no product identity"))
    }

    /// Return the normalized graph identity used for this result.
    #[getter]
    fn graph_content_id(&self) -> String {
        self.inner.trace.graph.to_string()
    }

    /// Return exact peak native bytes owned by evaluation.
    #[getter]
    fn peak_memory_bytes(&self) -> u64 {
        self.inner.report.peak_memory_bytes
    }

    /// Return the number of reachable evaluated nodes.
    #[getter]
    fn evaluated_nodes(&self) -> u64 {
        self.inner.report.counters.evaluated_nodes
    }

    /// Return the number of output sample positions produced across nodes.
    #[getter]
    fn produced_samples(&self) -> u64 {
        self.inner.report.counters.produced_samples
    }
}

impl PyRasterResult {
    pub(crate) const fn new(inner: EvaluationResult) -> Self {
        Self { inner }
    }
}

/// Immutable Python handle to one atomically published coverage evaluation result.
#[pyclass(name = "CoverageResult", module = "ferrastra._native", frozen)]
pub(crate) struct PyCoverageResult {
    inner: EvaluationResult,
}

#[pymethods]
impl PyCoverageResult {
    /// Return tightly packed immutable coverage samples as Python bytes.
    #[getter]
    fn pixels<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyBytes>> {
        product_pixels(&self.inner, py)
    }

    /// Return the coverage width in samples.
    #[getter]
    fn width(&self) -> u64 {
        self.inner.product.size().width
    }

    /// Return the coverage height in samples.
    #[getter]
    fn height(&self) -> u64 {
        self.inner.product.size().height
    }

    /// Return the tightly packed byte stride.
    #[getter]
    fn stride_bytes(&self) -> usize {
        self.inner.product.stride_bytes()
    }

    /// Return the canonical coverage format name.
    #[getter]
    fn format(&self) -> &'static str {
        match self.inner.product.format() {
            ProductFormat::Coverage(CoverageFormat::Coverage8) => "coverage8",
            ProductFormat::Coverage(CoverageFormat::Coverage16) => "coverage16",
            ProductFormat::Coverage(CoverageFormat::Coverage32Float) => "coverage32float",
            ProductFormat::Raster(_) => unreachable!("raster product wrapped as coverage"),
        }
    }

    /// Return the deterministic semantic product identity.
    #[getter]
    fn product_id(&self) -> PyResult<String> {
        product_id(&self.inner)
    }

    /// Return the normalized graph identity used for this result.
    #[getter]
    fn graph_content_id(&self) -> String {
        self.inner.trace.graph.to_string()
    }

    /// Return exact peak native bytes owned by evaluation.
    #[getter]
    fn peak_memory_bytes(&self) -> u64 {
        self.inner.report.peak_memory_bytes
    }

    /// Return the number of reachable evaluated nodes.
    #[getter]
    fn evaluated_nodes(&self) -> u64 {
        self.inner.report.counters.evaluated_nodes
    }

    /// Return the number of output sample positions produced across nodes.
    #[getter]
    fn produced_samples(&self) -> u64 {
        self.inner.report.counters.produced_samples
    }
}

impl PyCoverageResult {
    pub(crate) const fn new(inner: EvaluationResult) -> Self {
        Self { inner }
    }
}

fn product_pixels<'py>(
    result: &EvaluationResult,
    py: Python<'py>,
) -> PyResult<Bound<'py, PyBytes>> {
    let view = result.product.view().map_err(errors::graph)?;
    PyBytes::new_with(py, view.bytes().len(), |destination| {
        destination.copy_from_slice(view.bytes());
        Ok(())
    })
}

fn product_id(result: &EvaluationResult) -> PyResult<String> {
    result
        .report
        .product_id()
        .map(|identity| identity.to_string())
        .ok_or_else(|| errors::contract("published result has no product identity"))
}
