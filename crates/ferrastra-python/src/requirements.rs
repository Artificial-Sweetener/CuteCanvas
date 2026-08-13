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

//! Responsibility: Expose immutable native evaluation admission requirements to Python.
//!
//! Does not own: demand planning, operation memory rules, host budgets, or evaluation.

use ferrastra_engine::EvaluationRequirements;
use pyo3::prelude::*;

/// Immutable minimum budgets for one compiled regional evaluation.
#[pyclass(name = "EvaluationRequirements", module = "ferrastra._native", frozen)]
pub(crate) struct PyEvaluationRequirements {
    inner: EvaluationRequirements,
}

#[pymethods]
impl PyEvaluationRequirements {
    /// Return the minimum total native memory budget.
    #[getter]
    fn memory_bytes(&self) -> u64 {
        self.inner.memory_bytes
    }

    /// Return the minimum reusable scratch memory budget.
    #[getter]
    fn scratch_bytes(&self) -> u64 {
        self.inner.scratch_bytes
    }
}

impl PyEvaluationRequirements {
    pub(crate) const fn new(inner: EvaluationRequirements) -> Self {
        Self { inner }
    }
}
