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

//! Responsibility: Expose validated half-open integer regions to Python callers.
//!
//! Does not own: viewport coordinates, transforms, demand, damage, or raster storage.

use ferrastra_core::IntRect;
use pyo3::prelude::*;

use crate::errors;

/// Immutable half-open region in Ferrastra's integer pixel coordinate space.
#[pyclass(name = "Region", module = "ferrastra._native", frozen, skip_from_py_object)]
#[derive(Clone, Copy)]
pub(crate) struct PyRegion {
    inner: IntRect,
}

#[pymethods]
impl PyRegion {
    /// Construct a checked half-open integer region.
    #[new]
    fn new(x: i64, y: i64, width: u64, height: u64) -> PyResult<Self> {
        IntRect::new(x, y, width, height).map(|inner| Self { inner }).map_err(errors::contract)
    }

    /// Return the horizontal origin.
    #[getter]
    fn x(&self) -> i64 {
        self.inner.origin().x
    }

    /// Return the vertical origin.
    #[getter]
    fn y(&self) -> i64 {
        self.inner.origin().y
    }

    /// Return the horizontal extent.
    #[getter]
    fn width(&self) -> u64 {
        self.inner.size().width
    }

    /// Return the vertical extent.
    #[getter]
    fn height(&self) -> u64 {
        self.inner.size().height
    }
}

impl PyRegion {
    pub(crate) const fn inner(&self) -> IntRect {
        self.inner
    }
}
