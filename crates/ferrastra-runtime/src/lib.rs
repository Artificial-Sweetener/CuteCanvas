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

//! Responsibility: Expose bounded spatial planning, evaluation, publication, and trace contracts.
//!
//! Does not own: operation implementations, graph mutation, source editing, bindings, or host policy.

mod damage;
mod demand;
mod error;
mod evaluation;
mod parameters;
mod product_key;
mod registry;
mod requirements;
mod source;
mod trace;

pub use damage::propagate_damage;
pub use error::EvaluationError;
pub use evaluation::{EvaluationResult, evaluate};
pub use registry::{OperationSet, RegistryError};
pub use requirements::{EvaluationRequirements, evaluation_requirements};
pub use source::{ImageSourceProvider, ImageSourceStores};
pub use trace::{EvaluationTrace, NodeTrace};
