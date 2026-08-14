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

//! Responsibility: Own canonical immutable packed raster bytes and their strong source identity.
//!
//! Does not own: mutable edits, sparse tiling, graph nodes, sampling, conversion, or caching.

use std::fmt;
use std::sync::Arc;

use ferrastra_core::{
    ContentId, IntSize, ProductFormat, ProductView, ProductViewError, RasterFormat,
};

/// Error returned before an invalid or oversized immutable raster can be allocated.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RasterProductError {
    /// The borrowed source view was not a color raster format.
    CoverageView,
    /// Canonical packed allocation size exceeded the addressable domain.
    LayoutOverflow,
    /// A validated source row could not be borrowed from its backing span.
    InvalidSourceSpan,
    /// Owned tightly packed bytes did not match the declared dimensions and format.
    LengthMismatch,
}

impl fmt::Display for RasterProductError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let message = match self {
            Self::CoverageView => "raster products require a color raster view",
            Self::LayoutOverflow => "canonical raster layout exceeds the addressable byte domain",
            Self::InvalidSourceSpan => "borrowed raster source span is inconsistent",
            Self::LengthMismatch => "owned raster byte length does not match its tight layout",
        };
        formatter.write_str(message)
    }
}

impl std::error::Error for RasterProductError {}

/// Strong content identity of one immutable raster source revision.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct RasterRevisionId(ContentId);

impl RasterRevisionId {
    /// Construct a source revision handle from canonical raster content identity.
    #[must_use]
    pub const fn from_content_id(content_id: ContentId) -> Self {
        Self(content_id)
    }

    /// Return the canonical content identity.
    #[must_use]
    pub const fn as_content_id(&self) -> &ContentId {
        &self.0
    }
}

impl fmt::Display for RasterRevisionId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

/// Immutable tightly packed native color raster product.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RasterProduct {
    revision: RasterRevisionId,
    size: IntSize,
    stride_bytes: usize,
    format: RasterFormat,
    bytes: Arc<[u8]>,
}

impl RasterProduct {
    /// Copy a validated borrowed color raster into canonical tightly packed owned storage.
    ///
    /// # Errors
    ///
    /// Returns [`RasterProductError`] for coverage input, unrepresentable layout, or an
    /// inconsistent source span.
    pub fn copy_from(view: ProductView<'_>) -> Result<Self, RasterProductError> {
        let ProductFormat::Raster(format) = view.format() else {
            return Err(RasterProductError::CoverageView);
        };
        let width =
            usize::try_from(view.size().width).map_err(|_| RasterProductError::LayoutOverflow)?;
        let height =
            usize::try_from(view.size().height).map_err(|_| RasterProductError::LayoutOverflow)?;
        let row_bytes = width
            .checked_mul(usize::from(format.bytes_per_pixel()))
            .ok_or(RasterProductError::LayoutOverflow)?;
        let length = row_bytes.checked_mul(height).ok_or(RasterProductError::LayoutOverflow)?;
        let mut bytes = Vec::with_capacity(length);
        for row in 0..height {
            let start =
                row.checked_mul(view.stride_bytes()).ok_or(RasterProductError::LayoutOverflow)?;
            let end = start.checked_add(row_bytes).ok_or(RasterProductError::LayoutOverflow)?;
            let source =
                view.bytes().get(start..end).ok_or(RasterProductError::InvalidSourceSpan)?;
            bytes.extend_from_slice(source);
        }
        Self::from_tight_bytes(bytes, view.size(), format)
    }

    /// Adopt an owned tightly packed buffer as an immutable raster without another pixel copy.
    ///
    /// # Errors
    ///
    /// Returns [`RasterProductError`] when dimensions overflow or `bytes` has the wrong length.
    pub fn from_tight_bytes(
        bytes: Vec<u8>,
        size: IntSize,
        format: RasterFormat,
    ) -> Result<Self, RasterProductError> {
        let width = usize::try_from(size.width).map_err(|_| RasterProductError::LayoutOverflow)?;
        let height =
            usize::try_from(size.height).map_err(|_| RasterProductError::LayoutOverflow)?;
        let stride_bytes = width
            .checked_mul(usize::from(format.bytes_per_pixel()))
            .ok_or(RasterProductError::LayoutOverflow)?;
        let expected_length =
            stride_bytes.checked_mul(height).ok_or(RasterProductError::LayoutOverflow)?;
        if bytes.len() != expected_length {
            return Err(RasterProductError::LengthMismatch);
        }
        let revision = RasterRevisionId(content_id(size, format, &bytes));
        Ok(Self { revision, size, stride_bytes, format, bytes: bytes.into() })
    }

    /// Return the strong immutable source revision.
    #[must_use]
    pub const fn revision(&self) -> RasterRevisionId {
        self.revision
    }

    /// Return the exact sample dimensions.
    #[must_use]
    pub const fn size(&self) -> IntSize {
        self.size
    }

    /// Return the canonical packed color format.
    #[must_use]
    pub const fn format(&self) -> RasterFormat {
        self.format
    }

    /// Return the canonical packed byte stride.
    #[must_use]
    pub const fn stride_bytes(&self) -> usize {
        self.stride_bytes
    }

    /// Return the exact retained byte count.
    #[must_use]
    pub fn retained_bytes(&self) -> u64 {
        u64::try_from(self.bytes.len()).unwrap_or(u64::MAX)
    }

    /// Borrow the immutable canonical raster layout.
    ///
    /// # Errors
    ///
    /// Returns [`ProductViewError`] if internal storage no longer satisfies its validated layout.
    pub fn view(&self) -> Result<ProductView<'_>, ProductViewError> {
        ProductView::new(
            &self.bytes,
            self.size,
            self.stride_bytes,
            ProductFormat::Raster(self.format),
        )
    }
}

fn content_id(size: IntSize, format: RasterFormat, bytes: &[u8]) -> ContentId {
    let mut hasher = blake3::Hasher::new();
    hasher.update(b"FERRASTRA_RASTER_SOURCE\0");
    hasher.update(&size.width.to_le_bytes());
    hasher.update(&size.height.to_le_bytes());
    hasher.update(&[format_tag(format)]);
    hasher.update(bytes);
    ContentId::from_bytes(*hasher.finalize().as_bytes())
}

const fn format_tag(format: RasterFormat) -> u8 {
    match format {
        RasterFormat::Rgba8PremultipliedEncoded => 0,
        RasterFormat::Rgba16PremultipliedLinear => 1,
        RasterFormat::Rgba32FloatPremultipliedLinear => 2,
    }
}
