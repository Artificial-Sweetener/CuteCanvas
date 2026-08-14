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

//! Responsibility: Translate native failures into stable Python exception categories.
//!
//! Does not own: native recovery, diagnostic rendering, logging, or retry policy.

use ferrastra_engine::EngineError;
use pyo3::create_exception;
use pyo3::exceptions::PyException;
use pyo3::prelude::*;

create_exception!(ferrastra, FerrastraError, PyException, "Base Ferrastra failure.");
create_exception!(
    ferrastra,
    GraphError,
    FerrastraError,
    "Invalid graph construction or compilation."
);
create_exception!(ferrastra, EvaluationError, FerrastraError, "Bounded graph evaluation failed.");
create_exception!(ferrastra, BufferError, FerrastraError, "Raster buffer validation failed.");

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    let py = module.py();
    module.add("FerrastraError", py.get_type::<FerrastraError>())?;
    module.add("GraphError", py.get_type::<GraphError>())?;
    module.add("EvaluationError", py.get_type::<EvaluationError>())?;
    module.add("BufferError", py.get_type::<BufferError>())?;
    Ok(())
}

pub(crate) fn graph(error: impl std::fmt::Display) -> PyErr {
    GraphError::new_err(error.to_string())
}

pub(crate) fn evaluation(error: &EngineError) -> PyErr {
    EvaluationError::new_err(error.to_string())
}

pub(crate) fn engine(error: &EngineError) -> PyErr {
    FerrastraError::new_err(error.to_string())
}

pub(crate) fn compile(error: &EngineError) -> PyErr {
    GraphError::new_err(error.to_string())
}

pub(crate) fn contract(error: impl std::fmt::Display) -> PyErr {
    FerrastraError::new_err(error.to_string())
}

pub(crate) fn buffer(message: &'static str) -> PyErr {
    BufferError::new_err(message)
}
