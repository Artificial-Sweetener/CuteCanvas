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

//! Responsibility: Expose canonical pure raster operation implementations and source contracts.
//!
//! Does not own: graph structure, product retention, evaluation scheduling, bindings, or Qt.

mod affine_bilinear;
mod affine_bilinear_cpu;
mod affine_contract;
mod affine_nearest;
mod affine_nearest_cpu;
mod coefficient_cache;
mod coverage_affine;
mod coverage_affine_cpu;
mod coverage_area_cpu;
mod coverage_source;
mod definition_error;
mod identity;
mod lanczos3;
mod lanczos3_view;
mod lanczos_coefficients;
mod lanczos_cpu;
mod lanczos_operation;
mod raster_color;
mod raster_source;
mod sampling_contract;

pub use affine_bilinear::AffineBilinearOperation;
pub use affine_nearest::AffineNearestOperation;
pub use coverage_affine::CoverageAffineOperation;
pub use coverage_source::CoverageSourceOperation;
pub use definition_error::OperationDefinitionError;
pub use identity::IdentityOperation;
pub use lanczos3::Lanczos3Operation;
pub use lanczos3_view::Lanczos3ViewOperation;
pub use raster_source::RasterSourceOperation;
