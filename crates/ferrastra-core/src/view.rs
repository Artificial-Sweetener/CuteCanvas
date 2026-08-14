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

//! Responsibility: Define validated borrowed byte views over raster-like products.
//!
//! Does not own: allocation, product retention, format conversion, sampling, or publication.

use std::fmt;

use crate::{IntSize, ProductFormat};

/// Error returned when a borrowed product layout is not representable or fully backed.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProductViewError {
    /// One packed row is wider than the declared byte stride.
    RowExceedsStride,
    /// The byte span required by the layout exceeds the borrowed buffer.
    BufferTooShort,
    /// The required byte span cannot be represented on this platform.
    LayoutOverflow,
}

impl fmt::Display for ProductViewError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let message = match self {
            Self::RowExceedsStride => "packed product row exceeds its byte stride",
            Self::BufferTooShort => "borrowed product buffer is shorter than its declared layout",
            Self::LayoutOverflow => "borrowed product layout exceeds the addressable byte domain",
        };
        formatter.write_str(message)
    }
}

impl std::error::Error for ProductViewError {}

/// Validated immutable borrowed view of a packed raster or coverage product.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ProductView<'a> {
    bytes: &'a [u8],
    size: IntSize,
    stride_bytes: usize,
    format: ProductFormat,
}

impl<'a> ProductView<'a> {
    /// Validate and borrow a raster-like product layout.
    ///
    /// # Errors
    ///
    /// Returns [`ProductViewError`] when the stride, buffer length, or addressable span is invalid.
    pub fn new(
        bytes: &'a [u8],
        size: IntSize,
        stride_bytes: usize,
        format: ProductFormat,
    ) -> Result<Self, ProductViewError> {
        validate_layout(bytes.len(), size, stride_bytes, format)?;
        Ok(Self { bytes, size, stride_bytes, format })
    }

    /// Return the complete borrowed storage span, including row padding.
    #[must_use]
    pub const fn bytes(self) -> &'a [u8] {
        self.bytes
    }

    /// Return the sample dimensions.
    #[must_use]
    pub const fn size(self) -> IntSize {
        self.size
    }

    /// Return the distance between adjacent row starts, in bytes.
    #[must_use]
    pub const fn stride_bytes(self) -> usize {
        self.stride_bytes
    }

    /// Return the explicit packed sample format.
    #[must_use]
    pub const fn format(self) -> ProductFormat {
        self.format
    }
}

/// Validated mutable borrowed destination that remains unpublished while borrowed.
#[derive(Debug)]
pub struct ProductViewMut<'a> {
    bytes: &'a mut [u8],
    size: IntSize,
    stride_bytes: usize,
    format: ProductFormat,
}

impl<'a> ProductViewMut<'a> {
    /// Validate and mutably borrow an unpublished raster-like destination.
    ///
    /// # Errors
    ///
    /// Returns [`ProductViewError`] when the stride, buffer length, or addressable span is invalid.
    pub fn new(
        bytes: &'a mut [u8],
        size: IntSize,
        stride_bytes: usize,
        format: ProductFormat,
    ) -> Result<Self, ProductViewError> {
        validate_layout(bytes.len(), size, stride_bytes, format)?;
        Ok(Self { bytes, size, stride_bytes, format })
    }

    /// Return a shorter immutable borrow of this destination.
    #[must_use]
    pub fn as_view(&self) -> ProductView<'_> {
        ProductView {
            bytes: self.bytes,
            size: self.size,
            stride_bytes: self.stride_bytes,
            format: self.format,
        }
    }

    /// Return the complete mutable storage span, including row padding.
    #[must_use]
    pub fn bytes_mut(&mut self) -> &mut [u8] {
        self.bytes
    }

    /// Return the sample dimensions.
    #[must_use]
    pub const fn size(&self) -> IntSize {
        self.size
    }

    /// Return the distance between adjacent row starts, in bytes.
    #[must_use]
    pub const fn stride_bytes(&self) -> usize {
        self.stride_bytes
    }

    /// Return the explicit packed sample format.
    #[must_use]
    pub const fn format(&self) -> ProductFormat {
        self.format
    }
}

fn validate_layout(
    buffer_length: usize,
    size: IntSize,
    stride_bytes: usize,
    format: ProductFormat,
) -> Result<(), ProductViewError> {
    let width = usize::try_from(size.width).map_err(|_| ProductViewError::LayoutOverflow)?;
    let height = usize::try_from(size.height).map_err(|_| ProductViewError::LayoutOverflow)?;
    let row_bytes = width
        .checked_mul(usize::from(format.bytes_per_sample()))
        .ok_or(ProductViewError::LayoutOverflow)?;
    if row_bytes > stride_bytes {
        return Err(ProductViewError::RowExceedsStride);
    }
    let required_bytes = if width == 0 || height == 0 {
        0
    } else {
        height
            .checked_sub(1)
            .and_then(|row_count| row_count.checked_mul(stride_bytes))
            .and_then(|row_prefix| row_prefix.checked_add(row_bytes))
            .ok_or(ProductViewError::LayoutOverflow)?
    };
    if required_bytes > buffer_length {
        return Err(ProductViewError::BufferTooShort);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{ProductFormat, RasterFormat};

    #[test]
    fn borrowed_views_validate_explicit_byte_strides_and_buffer_spans() {
        let format = ProductFormat::Raster(RasterFormat::Rgba8PremultipliedEncoded);
        let size = IntSize { width: 2, height: 2 };
        let mut storage = [0_u8; 24];

        let mut view = ProductViewMut::new(&mut storage, size, 16, format)
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"));
        view.bytes_mut()[0] = 17;
        assert_eq!(view.as_view().bytes()[0], 17);
        assert_eq!(view.as_view().stride_bytes(), 16);
        assert_eq!(
            ProductView::new(&storage, size, 7, format),
            Err(ProductViewError::RowExceedsStride)
        );
        assert_eq!(
            ProductView::new(&storage[..23], size, 16, format),
            Err(ProductViewError::BufferTooShort)
        );
    }

    #[test]
    fn empty_views_require_no_backing_bytes_but_keep_their_layout() {
        let format = ProductFormat::Raster(RasterFormat::Rgba8PremultipliedEncoded);
        let view = ProductView::new(&[], IntSize { width: 0, height: u64::MAX }, 0, format)
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"));

        assert!(view.bytes().is_empty());
        assert_eq!(view.size().height, u64::MAX);
    }
}
