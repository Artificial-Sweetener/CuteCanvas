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

//! Responsibility: Define explicit product, pixel, coverage, color, alpha, edge, and quality semantics.
//!
//! Does not own: product allocation, format conversion, operation admission, or presentation policy.

/// Semantic kind of a typed graph product.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum ProductKind {
    /// Color raster samples.
    Raster,
    /// Scalar coverage samples.
    Coverage,
    /// Framework-neutral vector geometry.
    Vector,
    /// Mixed raster/vector graphic product.
    Graphic,
    /// Scalar numerical result.
    Scalar,
    /// Color value result.
    Color,
    /// Spatial transform value.
    Transform,
    /// Structured metadata result.
    Metadata,
}

/// Memory channel order of a raster format.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum ChannelOrder {
    /// Red, green, blue, alpha.
    Rgba,
    /// One coverage channel.
    Coverage,
}

/// Numerical representation of one channel component.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum ComponentRepresentation {
    /// Unsigned normalized eight-bit integer.
    UnsignedNormalized8,
    /// Unsigned normalized sixteen-bit integer.
    UnsignedNormalized16,
    /// IEEE 754 single-precision floating point.
    Float32,
}

impl ComponentRepresentation {
    /// Return the number of bytes occupied by one component.
    #[must_use]
    pub const fn byte_width(self) -> u8 {
        match self {
            Self::UnsignedNormalized8 => 1,
            Self::UnsignedNormalized16 => 2,
            Self::Float32 => 4,
        }
    }
}

/// Alpha representation carried by raster samples.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum AlphaMode {
    /// Color channels are multiplied by alpha.
    Premultiplied,
    /// Color channels are independent of alpha.
    Straight,
    /// The product has no alpha channel.
    Opaque,
}

/// Transfer function used to encode color channels.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum TransferFunction {
    /// Scene-linear or display-linear values.
    Linear,
    /// Standard RGB encoded values.
    Srgb,
}

/// Working color space used by an operation or product.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum WorkingSpace {
    /// Standard RGB primaries with the standard RGB transfer function.
    SrgbEncoded,
    /// Standard RGB primaries represented in linear light.
    SrgbLinear,
}

impl WorkingSpace {
    /// Return the transfer function used by this working space.
    #[must_use]
    pub const fn transfer_function(self) -> TransferFunction {
        match self {
            Self::SrgbEncoded => TransferFunction::Srgb,
            Self::SrgbLinear => TransferFunction::Linear,
        }
    }
}

/// Canonical raster memory format.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum RasterFormat {
    /// Eight-bit encoded RGBA with premultiplied alpha.
    Rgba8PremultipliedEncoded,
    /// Sixteen-bit linear RGBA with premultiplied alpha.
    Rgba16PremultipliedLinear,
    /// Single-precision linear RGBA with premultiplied alpha.
    Rgba32FloatPremultipliedLinear,
}

impl RasterFormat {
    /// Return the channel memory order.
    #[must_use]
    pub const fn channel_order(self) -> ChannelOrder {
        ChannelOrder::Rgba
    }

    /// Return the representation of each channel.
    #[must_use]
    pub const fn component_representation(self) -> ComponentRepresentation {
        match self {
            Self::Rgba8PremultipliedEncoded => ComponentRepresentation::UnsignedNormalized8,
            Self::Rgba16PremultipliedLinear => ComponentRepresentation::UnsignedNormalized16,
            Self::Rgba32FloatPremultipliedLinear => ComponentRepresentation::Float32,
        }
    }

    /// Return the alpha representation.
    #[must_use]
    pub const fn alpha_mode(self) -> AlphaMode {
        AlphaMode::Premultiplied
    }

    /// Return the expected working space.
    #[must_use]
    pub const fn working_space(self) -> WorkingSpace {
        match self {
            Self::Rgba8PremultipliedEncoded => WorkingSpace::SrgbEncoded,
            Self::Rgba16PremultipliedLinear | Self::Rgba32FloatPremultipliedLinear => {
                WorkingSpace::SrgbLinear
            }
        }
    }

    /// Return the exact byte width of one packed pixel.
    #[must_use]
    pub const fn bytes_per_pixel(self) -> u8 {
        self.component_representation().byte_width() * 4
    }
}

/// Canonical coverage memory format.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum CoverageFormat {
    /// Unsigned normalized eight-bit coverage.
    Coverage8,
    /// Unsigned normalized sixteen-bit coverage.
    Coverage16,
    /// Single-precision coverage.
    Coverage32Float,
}

impl CoverageFormat {
    /// Return the representation of each coverage sample.
    #[must_use]
    pub const fn component_representation(self) -> ComponentRepresentation {
        match self {
            Self::Coverage8 => ComponentRepresentation::UnsignedNormalized8,
            Self::Coverage16 => ComponentRepresentation::UnsignedNormalized16,
            Self::Coverage32Float => ComponentRepresentation::Float32,
        }
    }

    /// Return the exact byte width of one coverage sample.
    #[must_use]
    pub const fn bytes_per_sample(self) -> u8 {
        self.component_representation().byte_width()
    }
}

/// Concrete memory format of a raster-like product.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum ProductFormat {
    /// Color raster format.
    Raster(RasterFormat),
    /// Coverage raster format.
    Coverage(CoverageFormat),
}

impl ProductFormat {
    /// Return the product kind required by this format.
    #[must_use]
    pub const fn product_kind(self) -> ProductKind {
        match self {
            Self::Raster(_) => ProductKind::Raster,
            Self::Coverage(_) => ProductKind::Coverage,
        }
    }

    /// Return the packed byte width of one sample.
    #[must_use]
    pub const fn bytes_per_sample(self) -> u8 {
        match self {
            Self::Raster(format) => format.bytes_per_pixel(),
            Self::Coverage(format) => format.bytes_per_sample(),
        }
    }
}

/// Error returned when a product specification would contain contradictory semantics.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProductSpecError {
    /// A raster-like kind was requested without its required concrete format.
    MissingFormat,
}

impl std::fmt::Display for ProductSpecError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str("raster and coverage products require a concrete format")
    }
}

impl std::error::Error for ProductSpecError {}

/// Typed internally consistent product contract carried by a graph port or request.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct ProductSpec {
    kind: ProductKind,
    format: Option<ProductFormat>,
}

impl ProductSpec {
    /// Construct a color raster specification.
    #[must_use]
    pub const fn raster(format: RasterFormat) -> Self {
        Self { kind: ProductKind::Raster, format: Some(ProductFormat::Raster(format)) }
    }

    /// Construct a coverage specification.
    #[must_use]
    pub const fn coverage(format: CoverageFormat) -> Self {
        Self { kind: ProductKind::Coverage, format: Some(ProductFormat::Coverage(format)) }
    }

    /// Construct a non-raster product specification.
    ///
    /// # Errors
    ///
    /// Returns [`ProductSpecError::MissingFormat`] for raster or coverage kinds.
    pub const fn abstract_product(kind: ProductKind) -> Result<Self, ProductSpecError> {
        if matches!(kind, ProductKind::Raster | ProductKind::Coverage) {
            Err(ProductSpecError::MissingFormat)
        } else {
            Ok(Self { kind, format: None })
        }
    }

    /// Return the semantic product kind.
    #[must_use]
    pub const fn kind(self) -> ProductKind {
        self.kind
    }

    /// Return the concrete memory format of a raster-like product.
    #[must_use]
    pub const fn format(self) -> Option<ProductFormat> {
        self.format
    }
}

/// Sampling behavior outside finite source bounds.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum EdgeMode {
    /// Clamp coordinates to the nearest source sample.
    Clamp,
    /// Treat out-of-bounds samples as transparent black.
    Transparent,
    /// Reflect coordinates across source edges without repeating the edge sample.
    Reflect,
    /// Wrap coordinates periodically.
    Wrap,
}

/// Deterministic evaluation quality tier.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum QualityTier {
    /// Declared bounded approximation intended for active interaction.
    Interactive,
    /// Canonical operation result.
    Exact,
    /// Canonical semantics with a declared stricter precision policy.
    Export,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn raster_formats_define_complete_memory_and_color_semantics() {
        assert_eq!(RasterFormat::Rgba8PremultipliedEncoded.bytes_per_pixel(), 4);
        assert_eq!(
            RasterFormat::Rgba16PremultipliedLinear.working_space(),
            WorkingSpace::SrgbLinear
        );
        assert_eq!(
            RasterFormat::Rgba32FloatPremultipliedLinear.alpha_mode(),
            AlphaMode::Premultiplied
        );
    }

    #[test]
    fn product_specs_reject_implicit_raster_and_coverage_formats() {
        let raster = ProductSpec::raster(RasterFormat::Rgba8PremultipliedEncoded);
        let coverage = ProductSpec::coverage(CoverageFormat::Coverage8);
        let vector = ProductSpec::abstract_product(ProductKind::Vector)
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"));

        assert_eq!(raster.kind(), ProductKind::Raster);
        assert_eq!(coverage.format(), Some(ProductFormat::Coverage(CoverageFormat::Coverage8)));
        assert_eq!(
            ProductSpec::abstract_product(ProductKind::Raster),
            Err(ProductSpecError::MissingFormat)
        );
        assert_eq!(vector.kind(), ProductKind::Vector);
    }
}
