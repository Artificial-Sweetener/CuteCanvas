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

//! Responsibility: Expose immutable native products, source revisions, and explicit retention.
//!
//! Does not own: graph planning, operation implementations, scheduling, caches, Python, or Qt.

mod coverage_product;
mod coverage_source_store;
mod image_product;
mod raster_product;
mod source_store;

pub use coverage_product::{CoverageProduct, CoverageProductError, CoverageRevisionId};
pub use coverage_source_store::{CoverageLease, CoverageSourceStore};
pub use image_product::{ImageProduct, ImageProductError};
pub use raster_product::{RasterProduct, RasterProductError, RasterRevisionId};
pub use source_store::{RasterLease, RasterSourceStore, RetentionError};
