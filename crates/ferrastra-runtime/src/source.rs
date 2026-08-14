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

//! Responsibility: Define injected immutable raster and coverage source lookup boundaries.
//!
//! Does not own: source mutation, graph bindings, retention policy, operation semantics, or caches.

use ferrastra_core::ContentId;
use ferrastra_store::{CoverageLease, CoverageSourceStore, RasterLease, RasterSourceStore};

/// Read-only typed source resolver used for the bounded lifetime of one evaluation.
pub trait ImageSourceProvider {
    /// Lease the exact immutable raster revision, if retained.
    fn lease_raster(&self, revision: &ContentId) -> Option<RasterLease>;

    /// Lease the exact immutable coverage revision, if retained.
    fn lease_coverage(&self, revision: &ContentId) -> Option<CoverageLease>;
}

/// Pair independently retained raster and coverage source stores for evaluation.
pub struct ImageSourceStores<'a> {
    /// Immutable raster revisions.
    pub rasters: &'a RasterSourceStore,
    /// Immutable coverage revisions.
    pub coverages: &'a CoverageSourceStore,
}

impl ImageSourceProvider for ImageSourceStores<'_> {
    fn lease_raster(&self, revision: &ContentId) -> Option<RasterLease> {
        self.rasters.lease_content(revision)
    }

    fn lease_coverage(&self, revision: &ContentId) -> Option<CoverageLease> {
        self.coverages.lease_content(revision)
    }
}
