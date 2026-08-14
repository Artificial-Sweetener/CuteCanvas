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

//! Responsibility: Derive strong deterministic product keys from normalized graph and request state.
//!
//! Does not own: graph content identity, caching, source hashing, publication, or diagnostics.

use ferrastra_core::{ContentId, IntRect, ProductFormat, ProductKind, ProductSpec, QualityTier};
use ferrastra_graph::{GraphContentId, NodeId};

pub(crate) fn derive(
    graph: GraphContentId,
    node: NodeId,
    input_keys: &[ContentId],
    region: IntRect,
    output_port: &str,
    product: ProductSpec,
    quality: QualityTier,
) -> ContentId {
    let mut hasher = blake3::Hasher::new();
    hasher.update(b"FERRASTRA_PRODUCT_KEY\0");
    hasher.update(graph.as_content_id().as_bytes());
    hasher.update(&node.get().to_le_bytes());
    for input in input_keys {
        hasher.update(input.as_bytes());
    }
    hasher.update(&region.origin().x.to_le_bytes());
    hasher.update(&region.origin().y.to_le_bytes());
    hasher.update(&region.size().width.to_le_bytes());
    hasher.update(&region.size().height.to_le_bytes());
    hasher.update(output_port.as_bytes());
    hasher.update(&[product_kind(product.kind())]);
    if let Some(format) = product.format() {
        hasher.update(&[format_tag(format)]);
    }
    hasher.update(&[quality_tag(quality)]);
    ContentId::from_bytes(*hasher.finalize().as_bytes())
}

const fn product_kind(kind: ProductKind) -> u8 {
    match kind {
        ProductKind::Raster => 0,
        ProductKind::Coverage => 1,
        ProductKind::Vector => 2,
        ProductKind::Graphic => 3,
        ProductKind::Scalar => 4,
        ProductKind::Color => 5,
        ProductKind::Transform => 6,
        ProductKind::Metadata => 7,
    }
}

const fn format_tag(format: ProductFormat) -> u8 {
    match format {
        ProductFormat::Raster(ferrastra_core::RasterFormat::Rgba8PremultipliedEncoded) => 0x10,
        ProductFormat::Raster(ferrastra_core::RasterFormat::Rgba16PremultipliedLinear) => 0x11,
        ProductFormat::Raster(ferrastra_core::RasterFormat::Rgba32FloatPremultipliedLinear) => 0x12,
        ProductFormat::Coverage(ferrastra_core::CoverageFormat::Coverage8) => 0x20,
        ProductFormat::Coverage(ferrastra_core::CoverageFormat::Coverage16) => 0x21,
        ProductFormat::Coverage(ferrastra_core::CoverageFormat::Coverage32Float) => 0x22,
    }
}

const fn quality_tag(quality: QualityTier) -> u8 {
    match quality {
        QualityTier::Interactive => 0,
        QualityTier::Exact => 1,
        QualityTier::Export => 2,
    }
}
