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

//! Responsibility: Own canonical immutable packed coverage bytes and their source identity.
//!
//! Does not own: raster color products, mutable edits, graph nodes, sampling, or caching.

use std::fmt;
use std::sync::Arc;

use ferrastra_core::{
    ContentId, CoverageFormat, IntSize, ProductFormat, ProductView, ProductViewError,
};

/// Error returned before an invalid immutable coverage product can be allocated.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CoverageProductError {
    /// The borrowed source view was not a coverage format.
    RasterView,
    /// Canonical packed allocation size exceeded the addressable domain.
    LayoutOverflow,
    /// A validated source row could not be borrowed from its backing span.
    InvalidSourceSpan,
    /// Owned tightly packed bytes did not match the declared dimensions and format.
    LengthMismatch,
}

impl fmt::Display for CoverageProductError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::RasterView => "coverage products require a coverage view",
            Self::LayoutOverflow => "canonical coverage layout exceeds the addressable byte domain",
            Self::InvalidSourceSpan => "borrowed coverage source span is inconsistent",
            Self::LengthMismatch => "owned coverage byte length does not match its tight layout",
        })
    }
}

impl std::error::Error for CoverageProductError {}

/// Strong content identity of one immutable coverage source revision.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct CoverageRevisionId(ContentId);

impl CoverageRevisionId {
    /// Construct a source revision handle from canonical coverage content identity.
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

/// Immutable tightly packed native coverage product.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CoverageProduct {
    revision: CoverageRevisionId,
    size: IntSize,
    stride_bytes: usize,
    format: CoverageFormat,
    bytes: Arc<[u8]>,
}

impl CoverageProduct {
    /// Copy a validated borrowed coverage view into canonical tight storage.
    ///
    /// # Errors
    ///
    /// Returns [`CoverageProductError`] for raster input or an invalid layout.
    pub fn copy_from(view: ProductView<'_>) -> Result<Self, CoverageProductError> {
        let ProductFormat::Coverage(format) = view.format() else {
            return Err(CoverageProductError::RasterView);
        };
        let width =
            usize::try_from(view.size().width).map_err(|_| CoverageProductError::LayoutOverflow)?;
        let height = usize::try_from(view.size().height)
            .map_err(|_| CoverageProductError::LayoutOverflow)?;
        let row_bytes = width
            .checked_mul(usize::from(format.bytes_per_sample()))
            .ok_or(CoverageProductError::LayoutOverflow)?;
        let length = row_bytes.checked_mul(height).ok_or(CoverageProductError::LayoutOverflow)?;
        let mut bytes = Vec::with_capacity(length);
        for row in 0..height {
            let start =
                row.checked_mul(view.stride_bytes()).ok_or(CoverageProductError::LayoutOverflow)?;
            let end = start.checked_add(row_bytes).ok_or(CoverageProductError::LayoutOverflow)?;
            bytes.extend_from_slice(
                view.bytes().get(start..end).ok_or(CoverageProductError::InvalidSourceSpan)?,
            );
        }
        Self::from_tight_bytes(bytes, view.size(), format)
    }

    /// Adopt owned tightly packed coverage storage without another copy.
    ///
    /// # Errors
    ///
    /// Returns [`CoverageProductError`] for overflow or a length mismatch.
    pub fn from_tight_bytes(
        bytes: Vec<u8>,
        size: IntSize,
        format: CoverageFormat,
    ) -> Result<Self, CoverageProductError> {
        let width =
            usize::try_from(size.width).map_err(|_| CoverageProductError::LayoutOverflow)?;
        let height =
            usize::try_from(size.height).map_err(|_| CoverageProductError::LayoutOverflow)?;
        let stride_bytes = width
            .checked_mul(usize::from(format.bytes_per_sample()))
            .ok_or(CoverageProductError::LayoutOverflow)?;
        let expected =
            stride_bytes.checked_mul(height).ok_or(CoverageProductError::LayoutOverflow)?;
        if bytes.len() != expected {
            return Err(CoverageProductError::LengthMismatch);
        }
        let revision = CoverageRevisionId(content_id(size, format, &bytes));
        Ok(Self { revision, size, stride_bytes, format, bytes: bytes.into() })
    }

    /// Return the strong immutable source revision.
    #[must_use]
    pub const fn revision(&self) -> CoverageRevisionId {
        self.revision
    }

    /// Return exact sample dimensions.
    #[must_use]
    pub const fn size(&self) -> IntSize {
        self.size
    }

    /// Return the canonical coverage format.
    #[must_use]
    pub const fn format(&self) -> CoverageFormat {
        self.format
    }

    /// Return the tightly packed byte stride.
    #[must_use]
    pub const fn stride_bytes(&self) -> usize {
        self.stride_bytes
    }

    /// Return the exact retained byte count.
    #[must_use]
    pub fn retained_bytes(&self) -> u64 {
        u64::try_from(self.bytes.len()).unwrap_or(u64::MAX)
    }

    /// Borrow the immutable canonical coverage layout.
    ///
    /// # Errors
    ///
    /// Returns [`ProductViewError`] if storage violates its validated layout.
    pub fn view(&self) -> Result<ProductView<'_>, ProductViewError> {
        ProductView::new(
            &self.bytes,
            self.size,
            self.stride_bytes,
            ProductFormat::Coverage(self.format),
        )
    }
}

fn content_id(size: IntSize, format: CoverageFormat, bytes: &[u8]) -> ContentId {
    let mut hasher = blake3::Hasher::new();
    hasher.update(b"FERRASTRA_COVERAGE_SOURCE\0");
    hasher.update(&size.width.to_le_bytes());
    hasher.update(&size.height.to_le_bytes());
    hasher.update(&[format_tag(format)]);
    hasher.update(bytes);
    ContentId::from_bytes(*hasher.finalize().as_bytes())
}

const fn format_tag(format: CoverageFormat) -> u8 {
    match format {
        CoverageFormat::Coverage8 => 0,
        CoverageFormat::Coverage16 => 1,
        CoverageFormat::Coverage32Float => 2,
    }
}
