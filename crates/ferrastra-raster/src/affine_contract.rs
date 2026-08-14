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

//! Responsibility: Interpret exact output-to-source affine geometry parameters.
//!
//! Does not own: filter kernels, color policy, raster traversal, operation descriptors, or storage.

use ferrastra_core::{
    AffineTransform, EdgeMode, FloatPoint, IntRect, IntSize, OperationContractError,
    OperationParameters, ParameterValue,
};

use crate::sampling_contract::MAX_DIMENSION;

#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) struct AffineGeometryContract {
    pub(crate) source: IntSize,
    pub(crate) destination: IntSize,
    pub(crate) source_from_output: AffineTransform,
}

impl AffineGeometryContract {
    pub(crate) fn from_parameters(
        parameters: &OperationParameters,
    ) -> Result<Self, OperationContractError> {
        let source_from_output = AffineTransform::new([
            scalar(parameters, "source_m11")?,
            scalar(parameters, "source_m12")?,
            scalar(parameters, "source_m21")?,
            scalar(parameters, "source_m22")?,
            scalar(parameters, "source_tx")?,
            scalar(parameters, "source_ty")?,
        ])
        .map_err(|_| OperationContractError::InvalidParameters)?;
        source_from_output.inverse().map_err(|_| OperationContractError::InvalidParameters)?;
        Ok(Self {
            source: size(parameters, "source_width", "source_height")?,
            destination: size(parameters, "destination_width", "destination_height")?,
            source_from_output,
        })
    }

    pub(crate) fn validate_output_region(
        self,
        region: IntRect,
    ) -> Result<(), OperationContractError> {
        let domain = IntRect::new(0, 0, self.destination.width, self.destination.height)?;
        if domain.intersection(region) == region {
            Ok(())
        } else {
            Err(OperationContractError::OutputRegionUnavailable)
        }
    }

    pub(crate) fn source_demand(self, output: IntRect) -> Result<IntRect, OperationContractError> {
        self.source_demand_with_edge(output, EdgeMode::Transparent)
    }

    pub(crate) fn source_demand_with_edge(
        self,
        output: IntRect,
        edge: EdgeMode,
    ) -> Result<IntRect, OperationContractError> {
        self.validate_output_region(output)?;
        if output.is_empty() {
            return IntRect::new(0, 0, 0, 0).map_err(Into::into);
        }
        let bounds = mapped_bounds(self.source_from_output, output);
        match edge {
            EdgeMode::Transparent => clipped_source_rect(bounds, self.source),
            EdgeMode::Clamp => clamped_source_rect(bounds, self.source),
            EdgeMode::Reflect | EdgeMode::Wrap => Err(OperationContractError::InvalidParameters),
        }
    }

    pub(crate) fn source_area_demand(
        self,
        output: IntRect,
    ) -> Result<IntRect, OperationContractError> {
        self.validate_output_region(output)?;
        if output.is_empty() {
            return IntRect::new(0, 0, 0, 0).map_err(Into::into);
        }
        let mut bounds = mapped_bounds(self.source_from_output, output);
        let support_x = self.source_from_output.m11.abs().max(1.0) * 0.5;
        let support_y = self.source_from_output.m22.abs().max(1.0) * 0.5;
        bounds.left -= support_x;
        bounds.right += support_x;
        bounds.top -= support_y;
        bounds.bottom += support_y;
        clipped_source_rect(bounds, self.source)
    }

    pub(crate) fn forward_damage(
        self,
        input_damage: IntRect,
        edge: EdgeMode,
    ) -> Result<IntRect, OperationContractError> {
        let source_domain = IntRect::new(0, 0, self.source.width, self.source.height)?;
        let damage = source_domain.intersection(input_damage);
        if damage.is_empty() {
            return IntRect::new(0, 0, 0, 0).map_err(Into::into);
        }
        match edge {
            EdgeMode::Clamp if touches_boundary(damage, source_domain) => {
                return IntRect::new(0, 0, self.destination.width, self.destination.height)
                    .map_err(Into::into);
            }
            EdgeMode::Transparent | EdgeMode::Clamp => {}
            EdgeMode::Reflect | EdgeMode::Wrap => {
                return Err(OperationContractError::InvalidParameters);
            }
        }
        let output_from_source = self
            .source_from_output
            .inverse()
            .map_err(|_| OperationContractError::InvalidParameters)?;
        let expanded = damage.expand(1).map_err(|_| OperationContractError::InvalidParameters)?;
        let bounds = mapped_bounds(output_from_source, expanded);
        clipped_source_rect(bounds, self.destination)
    }

    #[allow(
        clippy::cast_precision_loss,
        reason = "validated output coordinates remain inside the i32-sized operation domain"
    )]
    pub(crate) fn source_coordinate(self, output_x: i64, output_y: i64) -> FloatPoint {
        self.source_from_output.map_point(FloatPoint { x: output_x as f64, y: output_y as f64 })
    }
}

fn touches_boundary(region: IntRect, domain: IntRect) -> bool {
    region.origin().x == domain.origin().x
        || region.origin().y == domain.origin().y
        || region.right() == domain.right()
        || region.bottom() == domain.bottom()
}

#[derive(Clone, Copy)]
struct FloatBounds {
    left: f64,
    top: f64,
    right: f64,
    bottom: f64,
}

#[allow(
    clippy::cast_precision_loss,
    reason = "validated region coordinates remain inside the i32-sized operation domain"
)]
fn mapped_bounds(transform: AffineTransform, region: IntRect) -> FloatBounds {
    let right = region.right() - 1;
    let bottom = region.bottom() - 1;
    let corners = [
        FloatPoint { x: region.origin().x as f64, y: region.origin().y as f64 },
        FloatPoint { x: right as f64, y: region.origin().y as f64 },
        FloatPoint { x: region.origin().x as f64, y: bottom as f64 },
        FloatPoint { x: right as f64, y: bottom as f64 },
    ]
    .map(|point| transform.map_point(point));
    FloatBounds {
        left: corners.iter().map(|point| point.x).fold(f64::INFINITY, f64::min),
        top: corners.iter().map(|point| point.y).fold(f64::INFINITY, f64::min),
        right: corners.iter().map(|point| point.x).fold(f64::NEG_INFINITY, f64::max),
        bottom: corners.iter().map(|point| point.y).fold(f64::NEG_INFINITY, f64::max),
    }
}

#[allow(
    clippy::cast_possible_truncation,
    reason = "finite mapped coordinates are clipped to validated i32-sized product domains"
)]
fn clipped_source_rect(
    bounds: FloatBounds,
    domain: IntSize,
) -> Result<IntRect, OperationContractError> {
    let domain_width =
        i64::try_from(domain.width).map_err(|_| OperationContractError::InvalidParameters)?;
    let domain_height =
        i64::try_from(domain.height).map_err(|_| OperationContractError::InvalidParameters)?;
    let left = (bounds.left.floor() as i64).clamp(0, domain_width);
    let top = (bounds.top.floor() as i64).clamp(0, domain_height);
    let right = ((bounds.right.floor() as i64) + 2).clamp(0, domain_width);
    let bottom = ((bounds.bottom.floor() as i64) + 2).clamp(0, domain_height);
    IntRect::new(
        left,
        top,
        u64::try_from(right.saturating_sub(left))
            .map_err(|_| OperationContractError::InvalidParameters)?,
        u64::try_from(bottom.saturating_sub(top))
            .map_err(|_| OperationContractError::InvalidParameters)?,
    )
    .map_err(Into::into)
}

#[allow(
    clippy::cast_possible_truncation,
    reason = "finite mapped coordinates are reduced to validated i32-sized product domains"
)]
fn clamped_source_rect(
    bounds: FloatBounds,
    domain: IntSize,
) -> Result<IntRect, OperationContractError> {
    let width =
        i64::try_from(domain.width).map_err(|_| OperationContractError::InvalidParameters)?;
    let height =
        i64::try_from(domain.height).map_err(|_| OperationContractError::InvalidParameters)?;
    let left = (bounds.left.floor() as i64).clamp(0, width - 1);
    let top = (bounds.top.floor() as i64).clamp(0, height - 1);
    let right = ((bounds.right.floor() as i64) + 2).clamp(1, width);
    let bottom = ((bounds.bottom.floor() as i64) + 2).clamp(1, height);
    IntRect::new(
        left.min(right - 1),
        top.min(bottom - 1),
        u64::try_from(right - left.min(right - 1))
            .map_err(|_| OperationContractError::InvalidParameters)?,
        u64::try_from(bottom - top.min(bottom - 1))
            .map_err(|_| OperationContractError::InvalidParameters)?,
    )
    .map_err(Into::into)
}

fn size(
    parameters: &OperationParameters,
    width: &str,
    height: &str,
) -> Result<IntSize, OperationContractError> {
    Ok(IntSize { width: dimension(parameters, width)?, height: dimension(parameters, height)? })
}

fn dimension(parameters: &OperationParameters, name: &str) -> Result<u64, OperationContractError> {
    let Some(ParameterValue::Integer(value)) = parameters.get_named(name) else {
        return Err(OperationContractError::InvalidParameters);
    };
    if !(1..=MAX_DIMENSION).contains(value) {
        return Err(OperationContractError::InvalidParameters);
    }
    u64::try_from(*value).map_err(|_| OperationContractError::InvalidParameters)
}

fn scalar(parameters: &OperationParameters, name: &str) -> Result<f64, OperationContractError> {
    let Some(ParameterValue::Scalar(value)) = parameters.get_named(name) else {
        return Err(OperationContractError::InvalidParameters);
    };
    Ok(value.get())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn clamped_boundary_damage_covers_every_destination_that_can_repeat_it() {
        let contract = AffineGeometryContract {
            source: IntSize { width: 4, height: 4 },
            destination: IntSize { width: 12, height: 8 },
            source_from_output: AffineTransform::IDENTITY,
        };
        let right_edge = IntRect::new(3, 1, 1, 1)
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"));

        assert_eq!(
            contract.forward_damage(right_edge, EdgeMode::Clamp),
            IntRect::new(0, 0, 12, 8).map_err(Into::into)
        );
    }

    #[test]
    fn transparent_boundary_damage_remains_spatially_bounded() {
        let contract = AffineGeometryContract {
            source: IntSize { width: 4, height: 4 },
            destination: IntSize { width: 12, height: 8 },
            source_from_output: AffineTransform::IDENTITY,
        };
        let right_edge = IntRect::new(3, 1, 1, 1)
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"));
        let full_destination = IntRect::new(0, 0, 12, 8)
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"));

        assert_ne!(
            contract
                .forward_damage(right_edge, EdgeMode::Transparent)
                .unwrap_or_else(|error| unreachable!("valid damage rejected: {error}")),
            full_destination
        );
    }
}
