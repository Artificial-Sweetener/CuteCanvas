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

//! Responsibility: Expose native package identity through Ferrastra's private Python boundary.
//!
//! Does not own: graphics products, kernels, graph planning, scheduling, caches,
//! application adapters, or public Python policy.

use pyo3::prelude::*;

/// Return the Cargo package version embedded in the native extension.
#[pyfunction]
#[must_use]
fn package_version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

/// Register Ferrastra's private native packaging boundary.
#[pymodule]
fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(package_version, module)?)?;
    module.add("__all__", ("package_version",))?;
    Ok(())
}
