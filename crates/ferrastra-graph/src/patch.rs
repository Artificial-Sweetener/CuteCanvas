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

//! Responsibility: Apply exact-precondition graph patches atomically to immutable revisions.
//!
//! Does not own: graph validation rules, revision allocation, history, undo, serialization, or execution.

use std::fmt;

use ferrastra_core::{
    CapabilitySet, ContentId, Diagnostic, DiagnosticError, OperationIdentity, ParameterId, PortId,
};

use crate::{
    GraphDefinition, GraphName, GraphRevisionId, InputBinding, NodeDefinition, NodeId, NodeOutput,
    OperationCatalog, ParameterBinding, validate_graph,
};

/// Exact fact that must still hold before a patch may be applied.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PatchPrecondition {
    /// A node must still use the expected operation semantics.
    NodeOperation {
        /// Target node.
        node: NodeId,
        /// Expected operation identity.
        expected: OperationIdentity,
    },
    /// A parameter binding must match exactly, including absence.
    Parameter {
        /// Target node.
        node: NodeId,
        /// Target parameter.
        parameter: ParameterId,
        /// Expected binding or absence.
        expected: Option<ParameterBinding>,
    },
    /// A source revision must match exactly, including absence.
    SourceRevision {
        /// Target node.
        node: NodeId,
        /// Expected immutable source revision or absence.
        expected: Option<ContentId>,
    },
}

/// One typed mutation inside an atomic graph patch.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum GraphChange {
    /// Add a node under a previously unused stable identity.
    AddNode {
        /// New node identity.
        node: NodeId,
        /// Complete node definition.
        definition: NodeDefinition,
    },
    /// Remove an existing node.
    RemoveNode {
        /// Existing node identity.
        node: NodeId,
    },
    /// Set or replace one typed parameter binding.
    SetParameter {
        /// Target node.
        node: NodeId,
        /// Target parameter.
        parameter: ParameterId,
        /// New binding.
        binding: ParameterBinding,
    },
    /// Replace the immutable source revision consumed by a source node.
    ReplaceSourceRevision {
        /// Target source node.
        node: NodeId,
        /// New immutable source revision.
        revision: ContentId,
    },
    /// Set or replace one input connection.
    ConnectInput {
        /// Target node.
        node: NodeId,
        /// Target input port.
        port: PortId,
        /// New source binding.
        binding: InputBinding,
    },
    /// Remove one input connection.
    DisconnectInput {
        /// Target node.
        node: NodeId,
        /// Target input port.
        port: PortId,
    },
    /// Set or replace a named graph output.
    SetOutput {
        /// Stable output name.
        name: GraphName,
        /// New node output.
        output: NodeOutput,
    },
    /// Remove a named graph output.
    RemoveOutput {
        /// Stable output name.
        name: GraphName,
    },
}

/// Serializable transactional patch between two immutable graph revisions.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GraphPatch {
    /// Exact base revision required by this patch.
    pub base_revision: GraphRevisionId,
    /// Revision assigned only after successful validation and publication.
    pub next_revision: GraphRevisionId,
    /// Exact facts checked before any change is applied.
    pub preconditions: Box<[PatchPrecondition]>,
    /// Ordered typed changes applied to a private candidate definition.
    pub changes: Box<[GraphChange]>,
}

/// Error returned without publishing a candidate graph revision.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PatchError {
    /// The patch was created against another base revision.
    StaleBase,
    /// A declared exact precondition no longer holds.
    PreconditionFailed,
    /// A change referenced a node or output that does not exist.
    MissingTarget,
    /// An add operation reused an existing stable identity.
    DuplicateTarget,
    /// The private candidate failed graph validation.
    Validation(Box<[Diagnostic]>),
    /// An internal stable diagnostic declaration was invalid.
    Diagnostic(DiagnosticError),
}

impl fmt::Display for PatchError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let message = match self {
            Self::StaleBase => "graph patch base revision is stale",
            Self::PreconditionFailed => "graph patch precondition failed",
            Self::MissingTarget => "graph patch target does not exist",
            Self::DuplicateTarget => "graph patch target already exists",
            Self::Validation(_) => "graph patch candidate failed validation",
            Self::Diagnostic(error) => return error.fmt(formatter),
        };
        formatter.write_str(message)
    }
}

impl std::error::Error for PatchError {}

/// Apply a patch to private cloned records and publish only a valid complete revision.
///
/// # Errors
///
/// Returns [`PatchError`] when the base, a precondition, a target, or the candidate is invalid.
pub fn apply_patch(
    graph: &GraphDefinition,
    patch: &GraphPatch,
    catalog: &impl OperationCatalog,
    available_capabilities: &CapabilitySet,
) -> Result<GraphDefinition, PatchError> {
    if graph.revision_id() != patch.base_revision {
        return Err(PatchError::StaleBase);
    }
    if !patch.preconditions.iter().all(|item| holds(graph, item)) {
        return Err(PatchError::PreconditionFailed);
    }

    let mut records = graph.records_clone();
    for change in &patch.changes {
        apply_change(&mut records, change)?;
    }
    let candidate = GraphDefinition::new(
        graph.schema_version(),
        patch.next_revision,
        records,
        graph.authoring().clone(),
    );
    let report = validate_graph(&candidate, catalog, available_capabilities)
        .map_err(PatchError::Diagnostic)?;
    if !report.valid {
        return Err(PatchError::Validation(report.diagnostics));
    }
    Ok(candidate)
}

fn holds(graph: &GraphDefinition, precondition: &PatchPrecondition) -> bool {
    match precondition {
        PatchPrecondition::NodeOperation { node, expected } => {
            graph.nodes().get(node).is_some_and(|definition| definition.operation == *expected)
        }
        PatchPrecondition::Parameter { node, parameter, expected } => graph
            .nodes()
            .get(node)
            .is_some_and(|definition| definition.parameters.get(parameter) == expected.as_ref()),
        PatchPrecondition::SourceRevision { node, expected } => graph
            .nodes()
            .get(node)
            .is_some_and(|definition| definition.source_revision == *expected),
    }
}

fn apply_change(records: &mut crate::GraphRecords, change: &GraphChange) -> Result<(), PatchError> {
    match change {
        GraphChange::AddNode { node, definition } => {
            if records.nodes.insert(*node, definition.clone()).is_some() {
                return Err(PatchError::DuplicateTarget);
            }
        }
        GraphChange::RemoveNode { node } => {
            if records.nodes.remove(node).is_none() {
                return Err(PatchError::MissingTarget);
            }
        }
        GraphChange::SetParameter { node, parameter, binding } => {
            let definition = records.nodes.get_mut(node).ok_or(PatchError::MissingTarget)?;
            definition.parameters.insert(parameter.clone(), binding.clone());
        }
        GraphChange::ReplaceSourceRevision { node, revision } => {
            let definition = records.nodes.get_mut(node).ok_or(PatchError::MissingTarget)?;
            definition.source_revision = Some(*revision);
        }
        GraphChange::ConnectInput { node, port, binding } => {
            let definition = records.nodes.get_mut(node).ok_or(PatchError::MissingTarget)?;
            definition.inputs.insert(port.clone(), binding.clone());
        }
        GraphChange::DisconnectInput { node, port } => {
            let definition = records.nodes.get_mut(node).ok_or(PatchError::MissingTarget)?;
            if definition.inputs.remove(port).is_none() {
                return Err(PatchError::MissingTarget);
            }
        }
        GraphChange::SetOutput { name, output } => {
            records.outputs.insert(name.clone(), output.clone());
        }
        GraphChange::RemoveOutput { name } => {
            if records.outputs.remove(name).is_none() {
                return Err(PatchError::MissingTarget);
            }
        }
    }
    Ok(())
}
