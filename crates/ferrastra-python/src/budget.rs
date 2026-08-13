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

//! Responsibility: Expose caller-owned Python cancellation and bounded execution budgets.
//!
//! Does not own: scheduling, allocation, deadlines, operation execution, or host policy.

use std::num::NonZeroUsize;

use ferrastra_core::{CancellationToken, ExecutionBudget};
use pyo3::prelude::*;

use crate::errors;

/// Python handle to one cooperative cancellation state.
#[pyclass(name = "CancellationToken", module = "ferrastra._native", frozen, skip_from_py_object)]
#[derive(Clone, Default)]
pub(crate) struct PyCancellationToken {
    inner: CancellationToken,
}

#[pymethods]
impl PyCancellationToken {
    /// Construct an uncancelled token.
    #[new]
    fn new() -> Self {
        Self::default()
    }

    /// Request cancellation idempotently.
    fn cancel(&self) {
        self.inner.cancel();
    }

    /// Return whether cancellation has been requested.
    #[getter]
    fn is_cancelled(&self) -> bool {
        self.inner.is_cancelled()
    }
}

/// Immutable caller-owned limits for one Python evaluation request.
#[pyclass(name = "EvaluationBudget", module = "ferrastra._native", frozen, skip_from_py_object)]
#[derive(Clone)]
pub(crate) struct PyEvaluationBudget {
    inner: ExecutionBudget,
}

#[pymethods]
impl PyEvaluationBudget {
    /// Construct explicit total-memory, scratch, thread, and cancellation limits.
    #[new]
    #[pyo3(signature = (*, memory_bytes, scratch_bytes = 0, threads = 1, cancellation = None))]
    #[allow(
        clippy::needless_pass_by_value,
        reason = "PyO3 extracts the optional class handle at the FFI boundary"
    )]
    fn new(
        memory_bytes: u64,
        scratch_bytes: u64,
        threads: usize,
        cancellation: Option<PyRef<'_, PyCancellationToken>>,
    ) -> PyResult<Self> {
        let threads = NonZeroUsize::new(threads)
            .ok_or_else(|| errors::contract("evaluation thread budget must be positive"))?;
        let cancellation = cancellation
            .as_deref()
            .map_or_else(CancellationToken::new, |token| token.inner.clone());
        Ok(Self { inner: ExecutionBudget::new(threads, scratch_bytes, memory_bytes, cancellation) })
    }

    /// Return the maximum total native bytes owned by evaluation.
    #[getter]
    fn memory_bytes(&self) -> u64 {
        self.inner.memory_bytes
    }

    /// Return the maximum reusable scratch bytes.
    #[getter]
    fn scratch_bytes(&self) -> u64 {
        self.inner.scratch_bytes
    }

    /// Return the maximum worker-thread count.
    #[getter]
    fn threads(&self) -> usize {
        self.inner.threads.get()
    }
}

impl PyEvaluationBudget {
    pub(crate) fn inner(&self) -> ExecutionBudget {
        self.inner.clone()
    }
}
