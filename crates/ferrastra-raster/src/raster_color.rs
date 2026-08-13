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

//! Responsibility: Convert premultiplied encoded RGBA8 samples with bounded color tables.
//!
//! Does not own: spatial sampling, coefficient generation, formats, or image presentation.

use ferrastra_core::WorkingSpace;

const ENCODE_TABLE_INTERVALS: usize = 16_384;

#[derive(Clone, Debug, PartialEq)]
pub(crate) struct ColorPipeline {
    linear_premultiplied: Box<[f64]>,
    encoded_curve: Box<[f64]>,
}

impl ColorPipeline {
    pub(crate) fn new() -> Self {
        let mut linear_premultiplied = vec![0.0_f64; 256 * 256];
        for alpha in 1_u16..=255 {
            let alpha_unit = f64::from(alpha) / 255.0;
            for channel in 0_u16..=255 {
                let clamped = channel.min(alpha);
                let encoded = f64::from(clamped) / f64::from(alpha);
                linear_premultiplied[usize::from(alpha) * 256 + usize::from(channel)] =
                    srgb_decode(encoded) * alpha_unit;
            }
        }
        let encoded_curve = (0..=ENCODE_TABLE_INTERVALS)
            .map(|index| srgb_encode(index_as_unit(index)))
            .collect::<Vec<_>>()
            .into_boxed_slice();
        Self { linear_premultiplied: linear_premultiplied.into_boxed_slice(), encoded_curve }
    }

    pub(crate) fn decode(&self, sample: [u8; 4], working_space: WorkingSpace) -> [f64; 4] {
        let alpha = f64::from(sample[3]) / 255.0;
        if sample[3] == 0 {
            return [0.0; 4];
        }
        if working_space == WorkingSpace::SrgbEncoded {
            return [
                f64::from(sample[0].min(sample[3])) / 255.0,
                f64::from(sample[1].min(sample[3])) / 255.0,
                f64::from(sample[2].min(sample[3])) / 255.0,
                alpha,
            ];
        }
        let alpha_offset = usize::from(sample[3]) * 256;
        [
            self.linear_premultiplied[alpha_offset + usize::from(sample[0])],
            self.linear_premultiplied[alpha_offset + usize::from(sample[1])],
            self.linear_premultiplied[alpha_offset + usize::from(sample[2])],
            alpha,
        ]
    }

    pub(crate) fn encode(&self, sample: [f64; 4], working_space: WorkingSpace) -> [u8; 4] {
        let alpha = sample[3].clamp(0.0, 1.0);
        let mut result = [0_u8; 4];
        result[3] = quantize(alpha);
        for channel in 0..3 {
            let premultiplied = sample[channel].clamp(0.0, alpha);
            result[channel] = if working_space == WorkingSpace::SrgbLinear && alpha > f64::EPSILON {
                quantize(self.encode_linear(premultiplied / alpha) * alpha)
            } else {
                quantize(premultiplied)
            };
            result[channel] = result[channel].min(result[3]);
        }
        result
    }

    fn encode_linear(&self, value: f64) -> f64 {
        let position = value.clamp(0.0, 1.0) * intervals_as_f64();
        let lower = floor_as_usize(position);
        let upper = lower.saturating_add(1).min(ENCODE_TABLE_INTERVALS);
        let fraction = position - usize_as_f64(lower);
        self.encoded_curve[lower].mul_add(1.0 - fraction, self.encoded_curve[upper] * fraction)
    }
}

#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    reason = "the value is explicitly rounded and clamped to the complete u8 domain before conversion"
)]
fn quantize(value: f64) -> u8 {
    (value.mul_add(255.0, 0.5).floor().clamp(0.0, 255.0)) as u8
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
    reason = "the lookup coordinate is clamped to the finite table domain"
)]
fn floor_as_usize(value: f64) -> usize {
    value.floor() as usize
}

#[allow(
    clippy::cast_precision_loss,
    reason = "lookup-table indices are bounded well below the exact integer range of f64"
)]
fn usize_as_f64(value: usize) -> f64 {
    value as f64
}

fn intervals_as_f64() -> f64 {
    usize_as_f64(ENCODE_TABLE_INTERVALS)
}

fn index_as_unit(index: usize) -> f64 {
    usize_as_f64(index) / intervals_as_f64()
}
