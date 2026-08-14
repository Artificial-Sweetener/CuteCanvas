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

//! Responsibility: Retain and lease deduplicated immutable coverage revisions.
//!
//! Does not own: raster products, cache eviction, mutable editing, graphs, or scheduling.

use std::collections::BTreeMap;
use std::sync::Arc;

use ferrastra_core::ContentId;

use crate::{CoverageProduct, CoverageRevisionId, RetentionError};

/// Shared lease keeping one immutable coverage revision alive during evaluation.
#[derive(Clone, Debug)]
pub struct CoverageLease {
    product: Arc<CoverageProduct>,
}

impl CoverageLease {
    /// Return the leased immutable coverage product.
    #[must_use]
    pub fn product(&self) -> &CoverageProduct {
        &self.product
    }
}

/// Explicit retained set of deduplicated immutable coverage source revisions.
#[derive(Debug, Default)]
pub struct CoverageSourceStore {
    products: BTreeMap<CoverageRevisionId, Arc<CoverageProduct>>,
    retained_bytes: u64,
}

impl CoverageSourceStore {
    /// Construct an empty coverage source store.
    #[must_use]
    pub const fn new() -> Self {
        Self { products: BTreeMap::new(), retained_bytes: 0 }
    }

    /// Retain an immutable product and deduplicate equal canonical content.
    ///
    /// # Errors
    ///
    /// Returns [`RetentionError`] when exact retained-byte accounting overflows.
    pub fn insert(
        &mut self,
        product: CoverageProduct,
    ) -> Result<CoverageRevisionId, RetentionError> {
        let revision = product.revision();
        if self.products.contains_key(&revision) {
            return Ok(revision);
        }
        self.retained_bytes =
            self.retained_bytes.checked_add(product.retained_bytes()).ok_or(RetentionError)?;
        self.products.insert(revision, Arc::new(product));
        Ok(revision)
    }

    /// Lease one retained revision by canonical content identity.
    #[must_use]
    pub fn lease_content(&self, content_id: &ContentId) -> Option<CoverageLease> {
        self.products
            .get(&CoverageRevisionId::from_content_id(*content_id))
            .cloned()
            .map(|product| CoverageLease { product })
    }

    /// Return exact bytes retained by unique coverage products.
    #[must_use]
    pub const fn retained_bytes(&self) -> u64 {
        self.retained_bytes
    }

    /// Return the number of unique retained revisions.
    #[must_use]
    pub fn len(&self) -> usize {
        self.products.len()
    }

    /// Return whether no coverage revisions are retained.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.products.is_empty()
    }
}
