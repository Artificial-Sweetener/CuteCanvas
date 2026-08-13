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

//! Responsibility: Define checked half-open regions and finite two-dimensional transforms.
//!
//! Does not own: graph demand propagation, damage policy, raster sampling, or viewport mapping.

use std::fmt;

use crate::FiniteScalar;

/// Offset from an integer pixel origin to its sample center on either axis.
pub const SAMPLE_CENTER_OFFSET: f64 = 0.5;

/// Error returned when integer geometry cannot be represented exactly.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum GeometryError {
    /// A coordinate plus its extent exceeded the signed coordinate domain.
    CoordinateOverflow,
    /// A requested expansion exceeded the unsigned extent domain.
    ExtentOverflow,
}

impl fmt::Display for GeometryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let message = match self {
            Self::CoordinateOverflow => "region coordinate overflow",
            Self::ExtentOverflow => "region extent overflow",
        };
        formatter.write_str(message)
    }
}

impl std::error::Error for GeometryError {}

/// Integer point in Ferrastra's canonical pixel-coordinate space.
#[derive(Clone, Copy, Debug, Default, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct IntPoint {
    /// Horizontal coordinate.
    pub x: i64,
    /// Vertical coordinate.
    pub y: i64,
}

/// Non-negative integer extent.
#[derive(Clone, Copy, Debug, Default, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct IntSize {
    /// Horizontal extent.
    pub width: u64,
    /// Vertical extent.
    pub height: u64,
}

impl IntSize {
    /// Return whether either dimension is zero.
    #[must_use]
    pub const fn is_empty(self) -> bool {
        self.width == 0 || self.height == 0
    }

    /// Return the number of sample positions, rejecting multiplication overflow.
    ///
    /// # Errors
    ///
    /// Returns [`GeometryError::ExtentOverflow`] when the area exceeds `u64`.
    pub const fn checked_area(self) -> Result<u64, GeometryError> {
        match self.width.checked_mul(self.height) {
            Some(area) => Ok(area),
            None => Err(GeometryError::ExtentOverflow),
        }
    }
}

/// Validated half-open integer rectangle.
#[derive(Clone, Copy, Debug, Default, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct IntRect {
    origin: IntPoint,
    size: IntSize,
}

impl IntRect {
    /// Construct a region after proving that both exclusive ends are representable.
    ///
    /// # Errors
    ///
    /// Returns [`GeometryError::CoordinateOverflow`] when an exclusive edge is not representable.
    pub fn new(x: i64, y: i64, width: u64, height: u64) -> Result<Self, GeometryError> {
        let region = Self { origin: IntPoint { x, y }, size: IntSize { width, height } };
        region.checked_right()?;
        region.checked_bottom()?;
        Ok(region)
    }

    /// Return the region origin.
    #[must_use]
    pub const fn origin(self) -> IntPoint {
        self.origin
    }

    /// Return the region extent.
    #[must_use]
    pub const fn size(self) -> IntSize {
        self.size
    }

    /// Return whether the region contains no sample positions.
    #[must_use]
    pub const fn is_empty(self) -> bool {
        self.size.is_empty()
    }

    /// Return the exclusive horizontal end.
    #[must_use]
    pub fn right(self) -> i64 {
        self.checked_right()
            .unwrap_or_else(|_| unreachable!("validated region has an invalid right edge"))
    }

    /// Return the exclusive vertical end.
    #[must_use]
    pub fn bottom(self) -> i64 {
        self.checked_bottom()
            .unwrap_or_else(|_| unreachable!("validated region has an invalid bottom edge"))
    }

    /// Return whether the half-open region contains `point`.
    #[must_use]
    pub fn contains(self, point: IntPoint) -> bool {
        !self.is_empty()
            && point.x >= self.origin.x
            && point.x < self.right()
            && point.y >= self.origin.y
            && point.y < self.bottom()
    }

    /// Return the exact intersection, including a canonical empty region when disjoint.
    #[must_use]
    pub fn intersection(self, other: Self) -> Self {
        let left = self.origin.x.max(other.origin.x);
        let top = self.origin.y.max(other.origin.y);
        let right = self.right().min(other.right());
        let bottom = self.bottom().min(other.bottom());
        if right <= left || bottom <= top {
            return Self { origin: IntPoint { x: left, y: top }, size: IntSize::default() };
        }
        Self {
            origin: IntPoint { x: left, y: top },
            size: IntSize {
                width: u64::try_from(right - left).unwrap_or_default(),
                height: u64::try_from(bottom - top).unwrap_or_default(),
            },
        }
    }

    /// Return the smallest representable region containing both regions.
    ///
    /// Empty regions do not enlarge a non-empty region.
    ///
    /// # Errors
    ///
    /// Returns [`GeometryError`] when the combined extent is not representable.
    pub fn union(self, other: Self) -> Result<Self, GeometryError> {
        if self.is_empty() {
            return Ok(other);
        }
        if other.is_empty() {
            return Ok(self);
        }
        let left = self.origin.x.min(other.origin.x);
        let top = self.origin.y.min(other.origin.y);
        let right = self.right().max(other.right());
        let bottom = self.bottom().max(other.bottom());
        let width = u64::try_from(right - left).map_err(|_| GeometryError::ExtentOverflow)?;
        let height = u64::try_from(bottom - top).map_err(|_| GeometryError::ExtentOverflow)?;
        Self::new(left, top, width, height)
    }

    /// Expand each edge by `radius`, rejecting coordinate or extent overflow.
    ///
    /// # Errors
    ///
    /// Returns [`GeometryError`] when the expanded coordinates or extents are not representable.
    pub fn expand(self, radius: u64) -> Result<Self, GeometryError> {
        let signed_radius = i64::try_from(radius).map_err(|_| GeometryError::ExtentOverflow)?;
        let x =
            self.origin.x.checked_sub(signed_radius).ok_or(GeometryError::CoordinateOverflow)?;
        let y =
            self.origin.y.checked_sub(signed_radius).ok_or(GeometryError::CoordinateOverflow)?;
        let doubled = radius.checked_mul(2).ok_or(GeometryError::ExtentOverflow)?;
        let width = self.size.width.checked_add(doubled).ok_or(GeometryError::ExtentOverflow)?;
        let height = self.size.height.checked_add(doubled).ok_or(GeometryError::ExtentOverflow)?;
        Self::new(x, y, width, height)
    }

    fn checked_right(self) -> Result<i64, GeometryError> {
        checked_end(self.origin.x, self.size.width)
    }

    fn checked_bottom(self) -> Result<i64, GeometryError> {
        checked_end(self.origin.y, self.size.height)
    }
}

/// Finite floating-point point in source-coordinate space.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct FloatPoint {
    /// Horizontal coordinate.
    pub x: f64,
    /// Vertical coordinate.
    pub y: f64,
}

/// Error returned when floating geometry is non-finite, invalid, or singular.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TransformError {
    /// At least one value was NaN or infinite.
    NonFinite,
    /// A floating extent was negative.
    NegativeExtent,
    /// A scale footprint was zero or negative.
    NonPositiveScale,
    /// A transform had no stable inverse.
    Singular,
}

impl fmt::Display for TransformError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let message = match self {
            Self::NonFinite => "geometry contains a non-finite value",
            Self::NegativeExtent => "floating region extent must be non-negative",
            Self::NonPositiveScale => "scale footprint must be positive on both axes",
            Self::Singular => "affine transform is singular",
        };
        formatter.write_str(message)
    }
}

impl std::error::Error for TransformError {}

/// Positive finite source-to-destination scale carried by spatial requests and identities.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct ScaleFootprint {
    source_units_per_output_x: FiniteScalar,
    source_units_per_output_y: FiniteScalar,
}

impl ScaleFootprint {
    /// Construct an axis-aligned source footprint for one output sample step.
    ///
    /// # Errors
    ///
    /// Returns [`TransformError::NonFinite`] for non-finite values or
    /// [`TransformError::NonPositiveScale`] for zero or negative values.
    pub fn new(
        source_units_per_output_x: f64,
        source_units_per_output_y: f64,
    ) -> Result<Self, TransformError> {
        let x =
            FiniteScalar::new(source_units_per_output_x).map_err(|_| TransformError::NonFinite)?;
        let y =
            FiniteScalar::new(source_units_per_output_y).map_err(|_| TransformError::NonFinite)?;
        if x.get() <= 0.0 || y.get() <= 0.0 {
            return Err(TransformError::NonPositiveScale);
        }
        Ok(Self { source_units_per_output_x: x, source_units_per_output_y: y })
    }

    /// Return the horizontal source-space step between adjacent output samples.
    #[must_use]
    pub const fn source_units_per_output_x(self) -> FiniteScalar {
        self.source_units_per_output_x
    }

    /// Return the vertical source-space step between adjacent output samples.
    #[must_use]
    pub const fn source_units_per_output_y(self) -> FiniteScalar {
        self.source_units_per_output_y
    }
}

/// Validated floating half-open rectangle in source-coordinate space.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct FloatRect {
    /// Horizontal origin.
    pub x: f64,
    /// Vertical origin.
    pub y: f64,
    /// Horizontal extent.
    pub width: f64,
    /// Vertical extent.
    pub height: f64,
}

impl FloatRect {
    /// Construct a finite rectangle with non-negative extents.
    ///
    /// # Errors
    ///
    /// Returns [`TransformError::NonFinite`] for non-finite values or
    /// [`TransformError::NegativeExtent`] for negative extents.
    pub fn new(x: f64, y: f64, width: f64, height: f64) -> Result<Self, TransformError> {
        if ![x, y, width, height].into_iter().all(f64::is_finite) {
            return Err(TransformError::NonFinite);
        }
        if width < 0.0 || height < 0.0 {
            return Err(TransformError::NegativeExtent);
        }
        Ok(Self {
            x: canonical_zero(x),
            y: canonical_zero(y),
            width: canonical_zero(width),
            height: canonical_zero(height),
        })
    }
}

/// Finite affine transform using the canonical column-vector convention.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct AffineTransform {
    /// Horizontal scale/skew coefficient.
    pub m11: f64,
    /// Vertical skew coefficient.
    pub m12: f64,
    /// Horizontal skew coefficient.
    pub m21: f64,
    /// Vertical scale/skew coefficient.
    pub m22: f64,
    /// Horizontal translation.
    pub tx: f64,
    /// Vertical translation.
    pub ty: f64,
}

impl AffineTransform {
    /// Identity transform.
    pub const IDENTITY: Self = Self { m11: 1.0, m12: 0.0, m21: 0.0, m22: 1.0, tx: 0.0, ty: 0.0 };

    /// Construct a transform after rejecting non-finite coefficients.
    ///
    /// # Errors
    ///
    /// Returns [`TransformError::NonFinite`] when any coefficient is non-finite.
    pub fn new(coefficients: [f64; 6]) -> Result<Self, TransformError> {
        if !coefficients.into_iter().all(f64::is_finite) {
            return Err(TransformError::NonFinite);
        }
        Ok(Self {
            m11: canonical_zero(coefficients[0]),
            m12: canonical_zero(coefficients[1]),
            m21: canonical_zero(coefficients[2]),
            m22: canonical_zero(coefficients[3]),
            tx: canonical_zero(coefficients[4]),
            ty: canonical_zero(coefficients[5]),
        })
    }

    /// Map one finite point.
    #[must_use]
    pub fn map_point(self, point: FloatPoint) -> FloatPoint {
        FloatPoint {
            x: self.m11.mul_add(point.x, self.m21.mul_add(point.y, self.tx)),
            y: self.m12.mul_add(point.x, self.m22.mul_add(point.y, self.ty)),
        }
    }

    /// Return the exact affine inverse when its determinant is finite and non-zero.
    ///
    /// # Errors
    ///
    /// Returns [`TransformError::Singular`] for a non-invertible transform or
    /// [`TransformError::NonFinite`] when inversion produces a non-finite coefficient.
    pub fn inverse(self) -> Result<Self, TransformError> {
        let determinant = self.m11.mul_add(self.m22, -(self.m21 * self.m12));
        if !determinant.is_finite() {
            return Err(TransformError::NonFinite);
        }
        if determinant == 0.0 {
            return Err(TransformError::Singular);
        }
        let inverse = 1.0 / determinant;
        Self::new([
            self.m22 * inverse,
            -self.m12 * inverse,
            -self.m21 * inverse,
            self.m11 * inverse,
            (self.m21 * self.ty - self.m22 * self.tx) * inverse,
            (self.m12 * self.tx - self.m11 * self.ty) * inverse,
        ])
    }
}

fn checked_end(origin: i64, extent: u64) -> Result<i64, GeometryError> {
    let signed_extent = i64::try_from(extent).map_err(|_| GeometryError::ExtentOverflow)?;
    origin.checked_add(signed_extent).ok_or(GeometryError::CoordinateOverflow)
}

const fn canonical_zero(value: f64) -> f64 {
    if value == 0.0 { 0.0 } else { value }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn integer_regions_are_checked_and_half_open() {
        let region = IntRect::new(-2, 4, 5, 3)
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"));

        assert!(region.contains(IntPoint { x: -2, y: 4 }));
        assert!(region.contains(IntPoint { x: 2, y: 6 }));
        assert!(!region.contains(IntPoint { x: 3, y: 6 }));
        assert!(!region.contains(IntPoint { x: 2, y: 7 }));
        assert_eq!(IntRect::new(i64::MAX, 0, 1, 1), Err(GeometryError::CoordinateOverflow));
    }

    #[test]
    fn intersection_and_expansion_preserve_exact_integer_geometry() {
        let first = IntRect::new(0, 0, 10, 10)
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"));
        let second = IntRect::new(8, -2, 10, 8)
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"));

        assert_eq!(
            first.intersection(second),
            IntRect::new(8, 0, 2, 6)
                .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"))
        );
        assert_eq!(first.expand(3), IntRect::new(-3, -3, 16, 16));
    }

    #[test]
    fn affine_inverse_round_trips_points() {
        let transform = AffineTransform::new([2.0, 0.5, -0.25, 3.0, 8.0, -4.0])
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"));
        let point = FloatPoint { x: 3.0, y: -7.0 };
        let restored = transform
            .inverse()
            .unwrap_or_else(|error| unreachable!("invertible fixture rejected: {error}"))
            .map_point(transform.map_point(point));

        assert!((restored.x - point.x).abs() < 1.0e-12);
        assert!((restored.y - point.y).abs() < 1.0e-12);
        assert_eq!(
            AffineTransform::new([1.0, 2.0, 2.0, 4.0, 0.0, 0.0]).and_then(AffineTransform::inverse),
            Err(TransformError::Singular)
        );
    }

    #[test]
    fn scale_footprints_are_finite_positive_identity_values() {
        let footprint = ScaleFootprint::new(0.5, 2.0)
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"));

        assert_eq!(
            footprint.source_units_per_output_x(),
            FiniteScalar::new(0.5)
                .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"))
        );
        assert_eq!(
            footprint.source_units_per_output_y(),
            FiniteScalar::new(2.0)
                .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"))
        );
        assert_eq!(ScaleFootprint::new(0.0, 1.0), Err(TransformError::NonPositiveScale));
        assert_eq!(ScaleFootprint::new(f64::NAN, 1.0), Err(TransformError::NonFinite));
    }
}
