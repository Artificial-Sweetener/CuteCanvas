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

//! Responsibility: Validate Python image buffers and copy canonical packed sample bytes.
//!
//! Does not own: source retention, product semantics, evaluation, or format conversion.

use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyBytesMethods, PyModule};

use crate::errors;

pub(crate) fn canonical_rgba8(
    py: Python<'_>,
    data: &Bound<'_, PyAny>,
    width: u64,
    height: u64,
    stride_bytes: usize,
) -> PyResult<Vec<u8>> {
    canonical_packed(py, data, width, height, stride_bytes, 4)
}

pub(crate) fn canonical_coverage8(
    py: Python<'_>,
    data: &Bound<'_, PyAny>,
    width: u64,
    height: u64,
    stride_bytes: usize,
) -> PyResult<Vec<u8>> {
    canonical_packed(py, data, width, height, stride_bytes, 1)
}

fn canonical_packed(
    py: Python<'_>,
    data: &Bound<'_, PyAny>,
    width: u64,
    height: u64,
    stride_bytes: usize,
    bytes_per_sample: usize,
) -> PyResult<Vec<u8>> {
    let builtins = PyModule::import(py, "builtins")?;
    let memoryview = builtins
        .getattr("memoryview")?
        .call1((data,))
        .map_err(|cause| buffer_cause(py, cause, "image data must expose a byte buffer"))?;
    if memoryview.getattr("ndim")?.extract::<usize>()? != 1 {
        return Err(errors::buffer("image data must be a one-dimensional byte buffer"));
    }
    if !memoryview.getattr("c_contiguous")?.extract::<bool>()? {
        return Err(errors::buffer("image data must be C-contiguous"));
    }
    if memoryview.getattr("format")?.extract::<String>()? != "B"
        || memoryview.getattr("itemsize")?.extract::<usize>()? != 1
    {
        return Err(errors::buffer("image data must contain unsigned bytes"));
    }
    let owned = memoryview.call_method0("tobytes")?;
    let source = owned.cast::<PyBytes>()?.as_bytes();
    let width = usize::try_from(width)
        .map_err(|_| errors::buffer("raster width exceeds the addressable buffer domain"))?;
    let height = usize::try_from(height)
        .map_err(|_| errors::buffer("raster height exceeds the addressable buffer domain"))?;
    let row_bytes = width
        .checked_mul(bytes_per_sample)
        .ok_or_else(|| errors::buffer("image row byte count overflowed"))?;
    if !is_empty(width, height) && stride_bytes < row_bytes {
        return Err(errors::buffer("image stride is smaller than one packed row"));
    }
    let required = required_span(row_bytes, height, stride_bytes)?;
    if source.len() < required {
        return Err(errors::buffer("image buffer is shorter than its declared layout"));
    }
    let packed_length = row_bytes
        .checked_mul(height)
        .ok_or_else(|| errors::buffer("packed image byte count overflowed"))?;
    let mut packed = Vec::with_capacity(packed_length);
    for row in 0..height {
        let start = row
            .checked_mul(stride_bytes)
            .ok_or_else(|| errors::buffer("image row offset overflowed"))?;
        let end = start
            .checked_add(row_bytes)
            .ok_or_else(|| errors::buffer("image row end overflowed"))?;
        let source_row = source
            .get(start..end)
            .ok_or_else(|| errors::buffer("image row lies outside the supplied buffer"))?;
        packed.extend_from_slice(source_row);
    }
    Ok(packed)
}

fn buffer_cause(py: Python<'_>, cause: PyErr, message: &'static str) -> PyErr {
    let translated = errors::buffer(message);
    translated.set_cause(py, Some(cause));
    translated
}

fn required_span(row_bytes: usize, height: usize, stride_bytes: usize) -> PyResult<usize> {
    if row_bytes == 0 || height == 0 {
        return Ok(0);
    }
    height
        .checked_sub(1)
        .and_then(|rows| rows.checked_mul(stride_bytes))
        .and_then(|offset| offset.checked_add(row_bytes))
        .ok_or_else(|| errors::buffer("image buffer span overflowed"))
}

const fn is_empty(width: usize, height: usize) -> bool {
    width == 0 || height == 0
}
