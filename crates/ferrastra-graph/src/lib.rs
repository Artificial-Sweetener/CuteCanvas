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

//! Responsibility: Expose Ferrastra's typed immutable graph and compilation contracts.
//!
//! Does not own: operation implementations, retained products, execution, bindings, or syntax.

mod builder;
mod compilation;
mod decode;
mod definition;
mod encode;
mod identity;
mod normalization;
mod patch;
mod serialization;
mod validation;
mod wire;

pub use definition::{
    DefinitionError, ExposedParameter, GraphAuthoring, GraphDefinition, GraphName, GraphRecords,
    InputBinding, NodeAuthoring, NodeDefinition, NodeOutput, ParameterBinding, UnknownRecord,
};

pub use builder::{BuilderError, GraphBuilder};
pub use compilation::{CompileError, CompiledNode, CompiledPlan, compile_graph};
pub use identity::{
    GraphContentId, GraphIdentityError, GraphRevisionId, GraphSchemaVersion, NodeId,
};
pub use patch::{GraphChange, GraphPatch, PatchError, PatchPrecondition, apply_patch};
pub use serialization::{GraphCodecError, deserialize_graph, serialize_graph};
pub use validation::{OperationCatalog, ValidationReport, validate_graph};
