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

//! Responsibility: Provide one typed runtime value over raster and coverage products.
//!
//! Does not own: source retention, operation semantics, evaluation, or conversion.

use ferrastra_core::{IntSize, ProductFormat, ProductView, ProductViewError};

use crate::{CoverageProduct, CoverageProductError, RasterProduct, RasterProductError};

/// Error returned when constructing a typed raster-like product.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ImageProductError {
    /// Color raster storage was invalid.
    Raster(RasterProductError),
    /// Coverage storage was invalid.
    Coverage(CoverageProductError),
}

impl std::fmt::Display for ImageProductError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Raster(error) => error.fmt(formatter),
            Self::Coverage(error) => error.fmt(formatter),
        }
    }
}

impl std::error::Error for ImageProductError {}

/// Immutable typed raster or coverage product published by evaluation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ImageProduct {
    /// Premultiplied color raster samples.
    Raster(RasterProduct),
    /// Scalar coverage samples.
    Coverage(CoverageProduct),
}

impl ImageProduct {
    /// Adopt owned tight bytes under their explicit product format.
    ///
    /// # Errors
    ///
    /// Returns [`ImageProductError`] when the selected typed layout is invalid.
    pub fn from_tight_bytes(
        bytes: Vec<u8>,
        size: IntSize,
        format: ProductFormat,
    ) -> Result<Self, ImageProductError> {
        match format {
            ProductFormat::Raster(format) => RasterProduct::from_tight_bytes(bytes, size, format)
                .map(Self::Raster)
                .map_err(ImageProductError::Raster),
            ProductFormat::Coverage(format) => {
                CoverageProduct::from_tight_bytes(bytes, size, format)
                    .map(Self::Coverage)
                    .map_err(ImageProductError::Coverage)
            }
        }
    }

    /// Copy a borrowed typed product into canonical tight storage.
    ///
    /// # Errors
    ///
    /// Returns [`ImageProductError`] when the borrowed layout is invalid.
    pub fn copy_from(view: ProductView<'_>) -> Result<Self, ImageProductError> {
        match view.format() {
            ProductFormat::Raster(_) => {
                RasterProduct::copy_from(view).map(Self::Raster).map_err(ImageProductError::Raster)
            }
            ProductFormat::Coverage(_) => CoverageProduct::copy_from(view)
                .map(Self::Coverage)
                .map_err(ImageProductError::Coverage),
        }
    }

    /// Return exact sample dimensions.
    #[must_use]
    pub const fn size(&self) -> IntSize {
        match self {
            Self::Raster(product) => product.size(),
            Self::Coverage(product) => product.size(),
        }
    }

    /// Return the explicit packed product format.
    #[must_use]
    pub const fn format(&self) -> ProductFormat {
        match self {
            Self::Raster(product) => ProductFormat::Raster(product.format()),
            Self::Coverage(product) => ProductFormat::Coverage(product.format()),
        }
    }

    /// Return the tightly packed byte stride.
    #[must_use]
    pub const fn stride_bytes(&self) -> usize {
        match self {
            Self::Raster(product) => product.stride_bytes(),
            Self::Coverage(product) => product.stride_bytes(),
        }
    }

    /// Return exact retained bytes.
    #[must_use]
    pub fn retained_bytes(&self) -> u64 {
        match self {
            Self::Raster(product) => product.retained_bytes(),
            Self::Coverage(product) => product.retained_bytes(),
        }
    }

    /// Borrow the immutable typed layout.
    ///
    /// # Errors
    ///
    /// Returns [`ProductViewError`] if internal storage violates its validated layout.
    pub fn view(&self) -> Result<ProductView<'_>, ProductViewError> {
        match self {
            Self::Raster(product) => product.view(),
            Self::Coverage(product) => product.view(),
        }
    }
}
