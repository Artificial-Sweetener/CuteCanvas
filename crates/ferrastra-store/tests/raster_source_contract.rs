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

//! Contract proof for immutable canonical raster source revisions and retention.

use ferrastra_core::{IntSize, ProductFormat, ProductView, RasterFormat};
use ferrastra_store::{RasterProduct, RasterSourceStore};

#[test]
fn padded_borrowed_sources_normalize_to_one_tight_content_revision() {
    let format = ProductFormat::Raster(RasterFormat::Rgba8PremultipliedEncoded);
    let size = IntSize { width: 2, height: 2 };
    let tight_bytes = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16];
    let padded_bytes = [1, 2, 3, 4, 5, 6, 7, 8, 99, 99, 99, 99, 9, 10, 11, 12, 13, 14, 15, 16];
    let tight = RasterProduct::copy_from(
        ProductView::new(&tight_bytes, size, 8, format)
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}")),
    )
    .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"));
    let padded = RasterProduct::copy_from(
        ProductView::new(&padded_bytes, size, 12, format)
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}")),
    )
    .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"));

    assert_eq!(tight.revision(), padded.revision());
    assert_eq!(tight.view().map(ProductView::bytes), Ok(tight_bytes.as_slice()));
}

#[test]
fn source_store_deduplicates_revisions_and_leases_without_copying() {
    let bytes = [0_u8; 16];
    let view = ProductView::new(
        &bytes,
        IntSize { width: 2, height: 2 },
        8,
        ProductFormat::Raster(RasterFormat::Rgba8PremultipliedEncoded),
    )
    .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"));
    let product = RasterProduct::copy_from(view)
        .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"));
    let duplicate = product.clone();
    let mut store = RasterSourceStore::new();
    let revision = store
        .insert(product)
        .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"));

    assert_eq!(store.insert(duplicate), Ok(revision));
    assert_eq!(store.len(), 1);
    assert_eq!(store.retained_bytes(), 16);
    assert_eq!(store.lease(revision).map(|lease| lease.product().revision()), Some(revision));
}
