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

//! Responsibility: Interpret exact axis-aligned sampling grids and their spatial mappings.
//!
//! Does not own: filter weights, raster traversal, operation descriptors, or execution.

use ferrastra_core::{
    EdgeMode, IntRect, IntSize, OperationContractError, OperationParameters, ParameterValue,
    WorkingSpace,
};

pub(crate) const MAX_DIMENSION: i64 = i32::MAX as i64;
const LANCZOS_SUPPORT: f64 = 3.0;

#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) struct AxisSampling {
    pub(crate) source_length: u64,
    pub(crate) output_length: u64,
    pub(crate) first_center: f64,
    pub(crate) source_step: f64,
    pub(crate) edge: EdgeMode,
}

impl AxisSampling {
    #[allow(
        clippy::cast_precision_loss,
        reason = "validated dimensions are bounded by i32::MAX and remain exactly representable"
    )]
    pub(crate) fn resize(
        source_length: u64,
        output_length: u64,
        edge: EdgeMode,
    ) -> Result<Self, OperationContractError> {
        if source_length == 0 || output_length == 0 {
            return Err(OperationContractError::InvalidParameters);
        }
        let source_step = source_length as f64 / output_length as f64;
        Self::new(source_length, output_length, source_step.mul_add(0.5, -0.5), source_step, edge)
    }

    pub(crate) fn new(
        source_length: u64,
        output_length: u64,
        first_center: f64,
        source_step: f64,
        edge: EdgeMode,
    ) -> Result<Self, OperationContractError> {
        if source_length == 0
            || output_length == 0
            || !first_center.is_finite()
            || !source_step.is_finite()
            || source_step <= 0.0
        {
            return Err(OperationContractError::InvalidParameters);
        }
        Ok(Self { source_length, output_length, first_center, source_step, edge })
    }

    #[allow(
        clippy::cast_precision_loss,
        reason = "validated output coordinates remain inside the i32-sized operation domain"
    )]
    pub(crate) fn source_coordinate(self, output_index: i64) -> f64 {
        (output_index as f64).mul_add(self.source_step, self.first_center)
    }

    pub(crate) fn filter_scale(self) -> f64 {
        (1.0 / self.source_step).min(1.0)
    }

    #[allow(
        clippy::cast_possible_truncation,
        reason = "validated coordinates and support remain within the widened i64 sampling domain"
    )]
    pub(crate) fn tap_bounds(self, output_index: i64) -> (i64, i64) {
        let center = self.source_coordinate(output_index);
        let support = LANCZOS_SUPPORT / self.filter_scale();
        let first = (center - support).floor() as i64 + 1;
        let last = (center + support).ceil() as i64 - 1;
        (first, last)
    }

    #[allow(
        clippy::cast_possible_truncation,
        clippy::cast_sign_loss,
        reason = "positive finite support is bounded by the validated sampling step"
    )]
    pub(crate) fn maximum_taps(self) -> u64 {
        (2.0 * LANCZOS_SUPPORT / self.filter_scale()).ceil() as u64 + 2
    }

    #[allow(
        clippy::cast_possible_truncation,
        clippy::cast_sign_loss,
        reason = "positive finite support is bounded by the validated sampling step"
    )]
    pub(crate) fn support_radius(self) -> u64 {
        (LANCZOS_SUPPORT / self.filter_scale()).ceil() as u64
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) struct LanczosContract {
    pub(crate) source: IntSize,
    pub(crate) destination: IntSize,
    pub(crate) horizontal: AxisSampling,
    pub(crate) vertical: AxisSampling,
    pub(crate) working_space: WorkingSpace,
}

impl LanczosContract {
    pub(crate) fn from_resize_parameters(
        parameters: &OperationParameters,
    ) -> Result<Self, OperationContractError> {
        let source = source_size(parameters)?;
        let destination = destination_size(parameters)?;
        let edge = edge_mode(parameters)?;
        Ok(Self {
            source,
            destination,
            horizontal: AxisSampling::resize(source.width, destination.width, edge)?,
            vertical: AxisSampling::resize(source.height, destination.height, edge)?,
            working_space: working_space(parameters)?,
        })
    }

    pub(crate) fn from_view_parameters(
        parameters: &OperationParameters,
    ) -> Result<Self, OperationContractError> {
        let source = source_size(parameters)?;
        let destination = destination_size(parameters)?;
        let edge = edge_mode(parameters)?;
        Ok(Self {
            source,
            destination,
            horizontal: AxisSampling::new(
                source.width,
                destination.width,
                scalar(parameters, "source_center_x")?,
                positive_scalar(parameters, "source_step_x")?,
                edge,
            )?,
            vertical: AxisSampling::new(
                source.height,
                destination.height,
                scalar(parameters, "source_center_y")?,
                positive_scalar(parameters, "source_step_y")?,
                edge,
            )?,
            working_space: working_space(parameters)?,
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
        self.validate_output_region(output)?;
        if output.is_empty() {
            return IntRect::new(0, 0, 0, 0).map_err(Into::into);
        }
        let (left, right) = required_axis(self.horizontal, output.origin().x, output.size().width)?;
        let (top, bottom) = required_axis(self.vertical, output.origin().y, output.size().height)?;
        IntRect::new(
            left,
            top,
            u64::try_from(right - left).map_err(|_| OperationContractError::InvalidParameters)?,
            u64::try_from(bottom - top).map_err(|_| OperationContractError::InvalidParameters)?,
        )
        .map_err(Into::into)
    }

    pub(crate) fn forward_damage(
        self,
        input_damage: IntRect,
    ) -> Result<IntRect, OperationContractError> {
        let source_domain = IntRect::new(0, 0, self.source.width, self.source.height)?;
        let damage = source_domain.intersection(input_damage);
        if damage.is_empty() {
            return IntRect::new(0, 0, 0, 0).map_err(Into::into);
        }
        let (left, right) = damaged_axis(self.horizontal, damage.origin().x, damage.size().width)?;
        let (top, bottom) = damaged_axis(self.vertical, damage.origin().y, damage.size().height)?;
        IntRect::new(
            left,
            top,
            u64::try_from(right - left).map_err(|_| OperationContractError::InvalidParameters)?,
            u64::try_from(bottom - top).map_err(|_| OperationContractError::InvalidParameters)?,
        )
        .map_err(Into::into)
    }

    #[allow(
        clippy::float_cmp,
        reason = "identity is the exact canonical tuple enabling byte-preserving execution"
    )]
    pub(crate) fn is_identity(self) -> bool {
        self.source == self.destination
            && self.horizontal.first_center == 0.0
            && self.horizontal.source_step == 1.0
            && self.vertical.first_center == 0.0
            && self.vertical.source_step == 1.0
    }
}

pub(crate) fn map_index(index: i64, length: u64, edge: EdgeMode) -> Option<i64> {
    let length = i64::try_from(length).ok()?;
    if (0..length).contains(&index) {
        return Some(index);
    }
    match edge {
        EdgeMode::Transparent => None,
        EdgeMode::Clamp => Some(index.clamp(0, length - 1)),
        EdgeMode::Wrap => Some(index.rem_euclid(length)),
        EdgeMode::Reflect if length == 1 => Some(0),
        EdgeMode::Reflect => {
            let period = (length - 1).checked_mul(2)?;
            let reflected = index.rem_euclid(period);
            Some(if reflected < length { reflected } else { period - reflected })
        }
    }
}

fn source_size(parameters: &OperationParameters) -> Result<IntSize, OperationContractError> {
    Ok(IntSize {
        width: dimension(parameters, "source_width")?,
        height: dimension(parameters, "source_height")?,
    })
}

fn destination_size(parameters: &OperationParameters) -> Result<IntSize, OperationContractError> {
    Ok(IntSize {
        width: dimension(parameters, "destination_width")?,
        height: dimension(parameters, "destination_height")?,
    })
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

fn positive_scalar(
    parameters: &OperationParameters,
    name: &str,
) -> Result<f64, OperationContractError> {
    let value = scalar(parameters, name)?;
    if value <= 0.0 {
        return Err(OperationContractError::InvalidParameters);
    }
    Ok(value)
}

fn enum_value<'a>(
    parameters: &'a OperationParameters,
    name: &str,
) -> Result<&'a str, OperationContractError> {
    let Some(ParameterValue::Enum(value)) = parameters.get_named(name) else {
        return Err(OperationContractError::InvalidParameters);
    };
    Ok(value.as_str())
}

pub(crate) fn edge_mode(
    parameters: &OperationParameters,
) -> Result<EdgeMode, OperationContractError> {
    match enum_value(parameters, "edge_mode")? {
        "clamp" => Ok(EdgeMode::Clamp),
        "transparent" => Ok(EdgeMode::Transparent),
        "reflect" => Ok(EdgeMode::Reflect),
        "wrap" => Ok(EdgeMode::Wrap),
        _ => Err(OperationContractError::InvalidParameters),
    }
}

fn working_space(parameters: &OperationParameters) -> Result<WorkingSpace, OperationContractError> {
    match enum_value(parameters, "working_space")? {
        "srgb_encoded" => Ok(WorkingSpace::SrgbEncoded),
        "srgb_linear" => Ok(WorkingSpace::SrgbLinear),
        _ => Err(OperationContractError::InvalidParameters),
    }
}

fn required_axis(
    sampling: AxisSampling,
    output_start: i64,
    output_length: u64,
) -> Result<(i64, i64), OperationContractError> {
    let output_end = output_start
        .checked_add(
            i64::try_from(output_length).map_err(|_| OperationContractError::InvalidParameters)?,
        )
        .ok_or(OperationContractError::InvalidParameters)?;
    let mut minimum = i64::MAX;
    let mut maximum = i64::MIN;
    for output_index in output_start..output_end {
        let (first, last) = sampling.tap_bounds(output_index);
        for source_index in first..=last {
            if let Some(mapped) = map_index(source_index, sampling.source_length, sampling.edge) {
                minimum = minimum.min(mapped);
                maximum = maximum.max(mapped);
            }
        }
    }
    if minimum > maximum { Ok((0, 0)) } else { Ok((minimum, maximum + 1)) }
}

fn damaged_axis(
    sampling: AxisSampling,
    damage_start: i64,
    damage_length: u64,
) -> Result<(i64, i64), OperationContractError> {
    if matches!(sampling.edge, EdgeMode::Reflect | EdgeMode::Wrap) {
        return Ok((
            0,
            i64::try_from(sampling.output_length)
                .map_err(|_| OperationContractError::InvalidParameters)?,
        ));
    }
    let damage_end = damage_start
        .checked_add(
            i64::try_from(damage_length).map_err(|_| OperationContractError::InvalidParameters)?,
        )
        .ok_or(OperationContractError::InvalidParameters)?;
    let first = lower_bound(sampling.output_length, |index| {
        i64::try_from(index).is_ok_and(|index| sampling.tap_bounds(index).1 >= damage_start)
    });
    let end = lower_bound(sampling.output_length, |index| {
        i64::try_from(index).is_ok_and(|index| sampling.tap_bounds(index).0 >= damage_end)
    });
    Ok((
        i64::try_from(first).map_err(|_| OperationContractError::InvalidParameters)?,
        i64::try_from(end).map_err(|_| OperationContractError::InvalidParameters)?,
    ))
}

fn lower_bound(length: u64, predicate: impl Fn(u64) -> bool) -> u64 {
    let mut low = 0_u64;
    let mut high = length;
    while low < high {
        let middle = low + (high - low) / 2;
        if predicate(middle) {
            high = middle;
        } else {
            low = middle + 1;
        }
    }
    low
}
