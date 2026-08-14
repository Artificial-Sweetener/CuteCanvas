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

//! Responsibility: Assemble typed graph records through a task-oriented Rust construction API.
//!
//! Does not own: catalog validation, revision allocation, patching, compilation, or execution.

use std::collections::BTreeMap;
use std::fmt;

use ferrastra_core::{ContentId, OperationIdentity, ParameterId, ParameterValue, PortId};

use crate::{
    GraphAuthoring, GraphDefinition, GraphName, GraphRecords, GraphRevisionId, GraphSchemaVersion,
    InputBinding, NodeAuthoring, NodeDefinition, NodeId, NodeOutput, ParameterBinding,
};

/// Error returned when graph construction targets missing or duplicate stable records.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BuilderError {
    /// A node identity was already present.
    DuplicateNode,
    /// A requested node identity was absent.
    MissingNode,
    /// A named graph output was already present.
    DuplicateOutput,
}

impl fmt::Display for BuilderError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let message = match self {
            Self::DuplicateNode => "graph builder node already exists",
            Self::MissingNode => "graph builder node does not exist",
            Self::DuplicateOutput => "graph builder output already exists",
        };
        formatter.write_str(message)
    }
}

impl std::error::Error for BuilderError {}

/// Mutable construction surface that publishes one immutable graph definition.
#[derive(Clone, Debug)]
pub struct GraphBuilder {
    schema_version: GraphSchemaVersion,
    revision_id: GraphRevisionId,
    records: GraphRecords,
    authoring: GraphAuthoring,
}

impl GraphBuilder {
    /// Begin constructing one explicit graph revision.
    #[must_use]
    pub fn new(schema_version: GraphSchemaVersion, revision_id: GraphRevisionId) -> Self {
        Self {
            schema_version,
            revision_id,
            records: GraphRecords::default(),
            authoring: GraphAuthoring::default(),
        }
    }

    /// Add an unconnected typed operation node.
    ///
    /// # Errors
    ///
    /// Returns [`BuilderError::DuplicateNode`] when `node` is already present.
    pub fn add_node(
        &mut self,
        node: NodeId,
        operation: OperationIdentity,
    ) -> Result<(), BuilderError> {
        if self.records.nodes.contains_key(&node) {
            return Err(BuilderError::DuplicateNode);
        }
        self.records.nodes.insert(
            node,
            NodeDefinition {
                operation,
                parameters: BTreeMap::new(),
                inputs: BTreeMap::new(),
                source_revision: None,
                unknown_records: Box::default(),
                authoring: NodeAuthoring::default(),
            },
        );
        Ok(())
    }

    /// Bind an immutable source revision to an existing source node.
    ///
    /// # Errors
    ///
    /// Returns [`BuilderError::MissingNode`] when `node` is absent.
    pub fn set_source_revision(
        &mut self,
        node: NodeId,
        revision: ContentId,
    ) -> Result<(), BuilderError> {
        self.node_mut(node)?.source_revision = Some(revision);
        Ok(())
    }

    /// Set a normalized constant operation parameter.
    ///
    /// # Errors
    ///
    /// Returns [`BuilderError::MissingNode`] when `node` is absent.
    pub fn set_parameter(
        &mut self,
        node: NodeId,
        parameter: ParameterId,
        value: ParameterValue,
    ) -> Result<(), BuilderError> {
        self.node_mut(node)?.parameters.insert(parameter, ParameterBinding::Constant(value));
        Ok(())
    }

    /// Connect one node output to one named input port.
    ///
    /// # Errors
    ///
    /// Returns [`BuilderError::MissingNode`] when either node is absent.
    pub fn connect(
        &mut self,
        source: NodeOutput,
        destination_node: NodeId,
        destination_port: PortId,
    ) -> Result<(), BuilderError> {
        if !self.records.nodes.contains_key(&source.node) {
            return Err(BuilderError::MissingNode);
        }
        self.node_mut(destination_node)?
            .inputs
            .insert(destination_port, InputBinding::Node(source));
        Ok(())
    }

    /// Publish one named graph output.
    ///
    /// # Errors
    ///
    /// Returns [`BuilderError::MissingNode`] for an absent node or
    /// [`BuilderError::DuplicateOutput`] for a reused output name.
    pub fn add_output(&mut self, name: GraphName, output: NodeOutput) -> Result<(), BuilderError> {
        if !self.records.nodes.contains_key(&output.node) {
            return Err(BuilderError::MissingNode);
        }
        if self.records.outputs.contains_key(&name) {
            return Err(BuilderError::DuplicateOutput);
        }
        self.records.outputs.insert(name, output);
        Ok(())
    }

    /// Replace graph-level authoring metadata excluded from computational identity.
    pub fn set_authoring(&mut self, authoring: GraphAuthoring) {
        self.authoring = authoring;
    }

    /// Publish the assembled immutable graph definition.
    #[must_use]
    pub fn build(self) -> GraphDefinition {
        GraphDefinition::new(self.schema_version, self.revision_id, self.records, self.authoring)
    }

    fn node_mut(&mut self, node: NodeId) -> Result<&mut NodeDefinition, BuilderError> {
        self.records.nodes.get_mut(&node).ok_or(BuilderError::MissingNode)
    }
}
