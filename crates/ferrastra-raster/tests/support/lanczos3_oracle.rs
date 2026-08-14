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

//! Independent direct two-dimensional oracle for the Lanczos3 pixel contract.

use std::f64::consts::PI;

#[derive(Clone, Copy)]
pub(crate) enum OracleEdge {
    Clamp,
    Transparent,
    Reflect,
    Wrap,
}

pub(crate) fn resize(
    source: &[u8],
    source_size: (usize, usize),
    destination_size: (usize, usize),
    edge: OracleEdge,
    linear: bool,
) -> Vec<u8> {
    let (source_width, source_height) = source_size;
    let (destination_width, destination_height) = destination_size;
    let mut destination = vec![0_u8; destination_width * destination_height * 4];
    for destination_y in 0..destination_height {
        let vertical = axis_weights(destination_y, source_height, destination_height, edge);
        for destination_x in 0..destination_width {
            let horizontal = axis_weights(destination_x, source_width, destination_width, edge);
            let mut result = [0.0_f64; 4];
            for &(source_y, vertical_weight) in &vertical {
                for &(source_x, horizontal_weight) in &horizontal {
                    let (Some(source_x), Some(source_y)) = (source_x, source_y) else {
                        continue;
                    };
                    let offset = (source_y * source_width + source_x) * 4;
                    let sample = decode(
                        source[offset..offset + 4]
                            .try_into()
                            .unwrap_or_else(|_| unreachable!("oracle sample is always four bytes")),
                        linear,
                    );
                    let weight = horizontal_weight * vertical_weight;
                    for channel in 0..4 {
                        result[channel] += sample[channel] * weight;
                    }
                }
            }
            let offset = (destination_y * destination_width + destination_x) * 4;
            destination[offset..offset + 4].copy_from_slice(&encode(result, linear));
        }
    }
    destination
}

pub(crate) fn sample_view(
    source: &[u8],
    source_size: (usize, usize),
    destination_size: (usize, usize),
    first_center: (f64, f64),
    source_step: (f64, f64),
    edge: OracleEdge,
    linear: bool,
) -> Vec<u8> {
    let (source_width, source_height) = source_size;
    let (destination_width, destination_height) = destination_size;
    let mut destination = vec![0_u8; destination_width * destination_height * 4];
    for destination_y in 0..destination_height {
        let vertical =
            sampled_axis_weights(destination_y, source_height, first_center.1, source_step.1, edge);
        for destination_x in 0..destination_width {
            let horizontal = sampled_axis_weights(
                destination_x,
                source_width,
                first_center.0,
                source_step.0,
                edge,
            );
            let mut result = [0.0_f64; 4];
            for &(source_y, vertical_weight) in &vertical {
                for &(source_x, horizontal_weight) in &horizontal {
                    let (Some(source_x), Some(source_y)) = (source_x, source_y) else {
                        continue;
                    };
                    let offset = (source_y * source_width + source_x) * 4;
                    let sample = decode(
                        source[offset..offset + 4]
                            .try_into()
                            .unwrap_or_else(|_| unreachable!("oracle sample is four bytes")),
                        linear,
                    );
                    let weight = horizontal_weight * vertical_weight;
                    for channel in 0..4 {
                        result[channel] += sample[channel] * weight;
                    }
                }
            }
            let offset = (destination_y * destination_width + destination_x) * 4;
            destination[offset..offset + 4].copy_from_slice(&encode(result, linear));
        }
    }
    destination
}

fn axis_weights(
    destination_index: usize,
    source_length: usize,
    destination_length: usize,
    edge: OracleEdge,
) -> Vec<(Option<usize>, f64)> {
    let source_length_f64 = usize_as_f64(source_length);
    let destination_length_f64 = usize_as_f64(destination_length);
    let scale = destination_length_f64 / source_length_f64;
    let filter_scale = scale.min(1.0);
    let center = (usize_as_f64(destination_index) + 0.5) / scale - 0.5;
    let support = 3.0 / filter_scale;
    let first = floor_as_i64(center - support) + 1;
    let last = ceil_as_i64(center + support) - 1;
    let mut weights = (first..=last)
        .map(|source_index| {
            let distance = (center - i64_as_f64(source_index)) * filter_scale;
            (map_index(source_index, source_length, edge), lanczos3(distance))
        })
        .collect::<Vec<_>>();
    let total = weights.iter().map(|(_, weight)| *weight).sum::<f64>();
    for (_, weight) in &mut weights {
        *weight /= total;
    }
    weights
}

fn sampled_axis_weights(
    destination_index: usize,
    source_length: usize,
    first_center: f64,
    source_step: f64,
    edge: OracleEdge,
) -> Vec<(Option<usize>, f64)> {
    let center = usize_as_f64(destination_index).mul_add(source_step, first_center);
    let filter_scale = (1.0 / source_step).min(1.0);
    let support = 3.0 / filter_scale;
    let first = floor_as_i64(center - support) + 1;
    let last = ceil_as_i64(center + support) - 1;
    let mut weights = (first..=last)
        .map(|source_index| {
            let distance = (center - i64_as_f64(source_index)) * filter_scale;
            (map_index(source_index, source_length, edge), lanczos3(distance))
        })
        .collect::<Vec<_>>();
    let total = weights.iter().map(|(_, weight)| *weight).sum::<f64>();
    for (_, weight) in &mut weights {
        *weight /= total;
    }
    weights
}

fn map_index(index: i64, length: usize, edge: OracleEdge) -> Option<usize> {
    let length = i64::try_from(length)
        .unwrap_or_else(|_| unreachable!("oracle fixtures fit the signed coordinate domain"));
    let mapped = if (0..length).contains(&index) {
        index
    } else {
        match edge {
            OracleEdge::Transparent => return None,
            OracleEdge::Clamp => index.clamp(0, length - 1),
            OracleEdge::Wrap => index.rem_euclid(length),
            OracleEdge::Reflect if length == 1 => 0,
            OracleEdge::Reflect => {
                let period = (length - 1) * 2;
                let reflected = index.rem_euclid(period);
                if reflected < length { reflected } else { period - reflected }
            }
        }
    };
    usize::try_from(mapped)
        .ok()
        .filter(|mapped| *mapped < usize::try_from(length).unwrap_or_default())
}

fn lanczos3(value: f64) -> f64 {
    let distance = value.abs();
    if distance <= f64::EPSILON {
        1.0
    } else if distance >= 3.0 {
        0.0
    } else {
        sinc(distance) * sinc(distance / 3.0)
    }
}

fn sinc(value: f64) -> f64 {
    let angle = PI * value;
    angle.sin() / angle
}

fn decode(sample: [u8; 4], linear: bool) -> [f64; 4] {
    let alpha = f64::from(sample[3]) / 255.0;
    if alpha <= f64::EPSILON {
        return [0.0; 4];
    }
    let encoded = [
        (f64::from(sample[0]) / 255.0).min(alpha),
        (f64::from(sample[1]) / 255.0).min(alpha),
        (f64::from(sample[2]) / 255.0).min(alpha),
    ];
    if !linear {
        return [encoded[0], encoded[1], encoded[2], alpha];
    }
    [
        srgb_decode(encoded[0] / alpha) * alpha,
        srgb_decode(encoded[1] / alpha) * alpha,
        srgb_decode(encoded[2] / alpha) * alpha,
        alpha,
    ]
}

fn encode(sample: [f64; 4], linear: bool) -> [u8; 4] {
    let alpha = sample[3].clamp(0.0, 1.0);
    let mut result = [0_u8; 4];
    result[3] = quantize(alpha);
    for channel in 0..3 {
        let premultiplied = sample[channel].clamp(0.0, alpha);
        result[channel] = if linear && alpha > f64::EPSILON {
            quantize(srgb_encode(premultiplied / alpha) * alpha)
        } else {
            quantize(premultiplied)
        }
        .min(result[3]);
    }
    result
}

fn srgb_decode(value: f64) -> f64 {
    if value <= 0.04045 { value / 12.92 } else { ((value + 0.055) / 1.055).powf(2.4) }
}

fn srgb_encode(value: f64) -> f64 {
    if value <= 0.003_130_8 { value * 12.92 } else { 1.055 * value.powf(1.0 / 2.4) - 0.055 }
}

#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    reason = "the oracle explicitly rounds and clamps to the complete u8 domain"
)]
fn quantize(value: f64) -> u8 {
    value.mul_add(255.0, 0.5).floor().clamp(0.0, 255.0) as u8
}

#[allow(
    clippy::cast_precision_loss,
    reason = "the deliberately small oracle fixtures are exactly representable in f64"
)]
fn usize_as_f64(value: usize) -> f64 {
    value as f64
}

#[allow(
    clippy::cast_precision_loss,
    reason = "the deliberately small oracle coordinates are exactly representable in f64"
)]
fn i64_as_f64(value: i64) -> f64 {
    value as f64
}

#[allow(
    clippy::cast_possible_truncation,
    reason = "the deliberately small oracle coordinates fit the signed coordinate domain"
)]
fn floor_as_i64(value: f64) -> i64 {
    value.floor() as i64
}

#[allow(
    clippy::cast_possible_truncation,
    reason = "the deliberately small oracle coordinates fit the signed coordinate domain"
)]
fn ceil_as_i64(value: f64) -> i64 {
    value.ceil() as i64
}
