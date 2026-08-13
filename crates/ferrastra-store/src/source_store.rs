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

//! Responsibility: Retain and lease deduplicated immutable raster source revisions.
//!
//! Does not own: cache eviction, mutable editing, graph source nodes, scheduling, or host policy.

use std::collections::BTreeMap;
use std::fmt;
use std::sync::Arc;

use ferrastra_core::ContentId;

use crate::{RasterProduct, RasterRevisionId};

/// Error returned when retained-byte accounting cannot represent another product.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RetentionError;

impl fmt::Display for RetentionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("retained raster bytes exceed the accounting domain")
    }
}

impl std::error::Error for RetentionError {}

/// Shared lease keeping one immutable raster revision alive during evaluation.
#[derive(Clone, Debug)]
pub struct RasterLease {
    product: Arc<RasterProduct>,
}

impl RasterLease {
    /// Return the leased immutable raster product.
    #[must_use]
    pub fn product(&self) -> &RasterProduct {
        &self.product
    }
}

/// Explicit retained set of deduplicated immutable raster source revisions.
#[derive(Debug, Default)]
pub struct RasterSourceStore {
    products: BTreeMap<RasterRevisionId, Arc<RasterProduct>>,
    retained_bytes: u64,
}

impl RasterSourceStore {
    /// Construct an empty source store.
    #[must_use]
    pub const fn new() -> Self {
        Self { products: BTreeMap::new(), retained_bytes: 0 }
    }

    /// Retain an immutable product, deduplicating equal canonical source content.
    ///
    /// # Errors
    ///
    /// Returns [`RetentionError`] when exact retained-byte accounting would overflow.
    pub fn insert(&mut self, product: RasterProduct) -> Result<RasterRevisionId, RetentionError> {
        let revision = product.revision();
        if self.products.contains_key(&revision) {
            return Ok(revision);
        }
        self.retained_bytes =
            self.retained_bytes.checked_add(product.retained_bytes()).ok_or(RetentionError)?;
        self.products.insert(revision, Arc::new(product));
        Ok(revision)
    }

    /// Lease one retained revision without copying its pixels.
    #[must_use]
    pub fn lease(&self, revision: RasterRevisionId) -> Option<RasterLease> {
        self.products.get(&revision).cloned().map(|product| RasterLease { product })
    }

    /// Lease one retained revision by its canonical content identity.
    #[must_use]
    pub fn lease_content(&self, content_id: &ContentId) -> Option<RasterLease> {
        self.lease(RasterRevisionId::from_content_id(*content_id))
    }

    /// Return whether a revision is available for evaluation.
    #[must_use]
    pub fn contains(&self, revision: RasterRevisionId) -> bool {
        self.products.contains_key(&revision)
    }

    /// Return exact bytes retained by unique source products.
    #[must_use]
    pub const fn retained_bytes(&self) -> u64 {
        self.retained_bytes
    }

    /// Return the number of unique retained revisions.
    #[must_use]
    pub fn len(&self) -> usize {
        self.products.len()
    }

    /// Return whether no source revisions are retained.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.products.is_empty()
    }
}
