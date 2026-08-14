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

//! Responsibility: Define immutable typed graph records and segregated authoring metadata.
//!
//! Does not own: validation against catalogs, patch application, compilation, execution, or syntax.

use std::collections::BTreeMap;
use std::fmt;

use ferrastra_core::{
    ContentId, OperationIdentity, ParameterId, ParameterType, ParameterValue, PortId, ProductSpec,
    Unit,
};

use crate::{GraphContentId, GraphRevisionId, GraphSchemaVersion, NodeId};

/// Error returned when a graph record cannot be represented canonically.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DefinitionError {
    /// A graph-facing name was empty or malformed.
    InvalidName,
    /// An unknown record kind contained no visible text.
    InvalidUnknownRecordKind,
}

impl fmt::Display for DefinitionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let message = match self {
            Self::InvalidName => "graph name is not canonical",
            Self::InvalidUnknownRecordKind => "unknown record kind must not be empty",
        };
        formatter.write_str(message)
    }
}

impl std::error::Error for DefinitionError {}

/// Stable lowercase identifier for graph inputs, outputs, and exposed parameters.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct GraphName(Box<str>);

impl GraphName {
    /// Validate and construct a graph-facing name.
    ///
    /// # Errors
    ///
    /// Returns [`DefinitionError::InvalidName`] when the value is not lowercase snake case.
    pub fn new(value: impl Into<Box<str>>) -> Result<Self, DefinitionError> {
        let value = value.into();
        let mut characters = value.bytes();
        let valid = characters.next().is_some_and(|first| first.is_ascii_lowercase())
            && characters.all(|character| {
                character.is_ascii_lowercase() || character.is_ascii_digit() || character == b'_'
            });
        if valid { Ok(Self(value)) } else { Err(DefinitionError::InvalidName) }
    }

    /// Return the canonical name text.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for GraphName {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.as_str())
    }
}

/// Opaque extension record retained even when its producer is unavailable.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UnknownRecord {
    kind: Box<str>,
    payload: Box<[u8]>,
}

impl UnknownRecord {
    /// Construct an opaque record with a non-empty kind identifier.
    ///
    /// # Errors
    ///
    /// Returns [`DefinitionError::InvalidUnknownRecordKind`] when `kind` has no visible text.
    pub fn new(
        kind: impl Into<Box<str>>,
        payload: impl Into<Box<[u8]>>,
    ) -> Result<Self, DefinitionError> {
        let kind = kind.into();
        if kind.trim().is_empty() {
            return Err(DefinitionError::InvalidUnknownRecordKind);
        }
        Ok(Self { kind, payload: payload.into() })
    }

    /// Return the preserved record-kind identifier.
    #[must_use]
    pub fn kind(&self) -> &str {
        &self.kind
    }

    /// Return the preserved opaque payload.
    #[must_use]
    pub fn payload(&self) -> &[u8] {
        &self.payload
    }
}

/// Output port of one stable authoring node.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct NodeOutput {
    /// Source node.
    pub node: NodeId,
    /// Named output port.
    pub port: PortId,
}

/// Source bound to one operation input port.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum InputBinding {
    /// Declared graph input.
    GraphInput(GraphName),
    /// Output of another graph node.
    Node(NodeOutput),
}

/// Value bound to one operation parameter.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ParameterBinding {
    /// Canonical constant value stored on the node.
    Constant(ParameterValue),
    /// Declared graph parameter resolved by the caller.
    Exposed(GraphName),
}

/// Authoring-only node data excluded from graph computational identity.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct NodeAuthoring {
    /// Optional human-facing label.
    pub label: Option<Box<str>>,
    /// Stable authoring annotations unused by compilation.
    pub annotations: BTreeMap<Box<str>, Box<str>>,
}

/// Immutable typed node definition.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NodeDefinition {
    /// Versioned operation semantics.
    pub operation: OperationIdentity,
    /// Typed normalized parameter bindings.
    pub parameters: BTreeMap<ParameterId, ParameterBinding>,
    /// Named input bindings.
    pub inputs: BTreeMap<PortId, InputBinding>,
    /// Optional immutable source revision consumed by source operations.
    pub source_revision: Option<ContentId>,
    /// Opaque computational records retained for forward compatibility.
    pub unknown_records: Box<[UnknownRecord]>,
    /// Authoring-only data excluded from computational identity.
    pub authoring: NodeAuthoring,
}

/// Declared graph parameter connected to one node parameter.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExposedParameter {
    /// Target node.
    pub node: NodeId,
    /// Target operation parameter.
    pub parameter: ParameterId,
    /// Accepted value type.
    pub parameter_type: ParameterType,
    /// Declared semantic unit.
    pub unit: Unit,
    /// Canonical default supplied when a caller omits the value.
    pub default: ParameterValue,
}

/// Authoring-only graph data excluded from computational identity.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct GraphAuthoring {
    /// Optional human-facing graph label.
    pub label: Option<Box<str>>,
    /// Stable authoring annotations unused by compilation.
    pub annotations: BTreeMap<Box<str>, Box<str>>,
}

/// Computational records assembled into one immutable graph revision.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct GraphRecords {
    /// Declared typed graph inputs.
    pub inputs: BTreeMap<GraphName, ProductSpec>,
    /// Declared parameters supplied by graph callers.
    pub exposed_parameters: BTreeMap<GraphName, ExposedParameter>,
    /// Typed operation nodes keyed by stable authoring identity.
    pub nodes: BTreeMap<NodeId, NodeDefinition>,
    /// Named graph outputs.
    pub outputs: BTreeMap<GraphName, NodeOutput>,
    /// Opaque computational records retained for forward compatibility.
    pub unknown_records: Box<[UnknownRecord]>,
}

/// Immutable versioned graph definition shared by every construction frontend.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GraphDefinition {
    schema_version: GraphSchemaVersion,
    revision_id: GraphRevisionId,
    content_id: GraphContentId,
    inputs: BTreeMap<GraphName, ProductSpec>,
    exposed_parameters: BTreeMap<GraphName, ExposedParameter>,
    nodes: BTreeMap<NodeId, NodeDefinition>,
    outputs: BTreeMap<GraphName, NodeOutput>,
    unknown_records: Box<[UnknownRecord]>,
    authoring: GraphAuthoring,
}

impl GraphDefinition {
    /// Construct an immutable definition and compute its normalized computational identity.
    #[must_use]
    pub fn new(
        schema_version: GraphSchemaVersion,
        revision_id: GraphRevisionId,
        records: GraphRecords,
        authoring: GraphAuthoring,
    ) -> Self {
        let content_id = crate::normalization::content_id(
            schema_version,
            &records.inputs,
            &records.exposed_parameters,
            &records.nodes,
            &records.outputs,
            &records.unknown_records,
        );
        Self {
            schema_version,
            revision_id,
            content_id,
            inputs: records.inputs,
            exposed_parameters: records.exposed_parameters,
            nodes: records.nodes,
            outputs: records.outputs,
            unknown_records: records.unknown_records,
            authoring,
        }
    }

    /// Return the canonical schema version.
    #[must_use]
    pub const fn schema_version(&self) -> GraphSchemaVersion {
        self.schema_version
    }

    /// Return this immutable lineage revision.
    #[must_use]
    pub const fn revision_id(&self) -> GraphRevisionId {
        self.revision_id
    }

    /// Return the normalized computational identity.
    #[must_use]
    pub const fn content_id(&self) -> GraphContentId {
        self.content_id
    }

    /// Return declared graph inputs in canonical name order.
    #[must_use]
    pub const fn inputs(&self) -> &BTreeMap<GraphName, ProductSpec> {
        &self.inputs
    }

    /// Return declared exposed parameters in canonical name order.
    #[must_use]
    pub const fn exposed_parameters(&self) -> &BTreeMap<GraphName, ExposedParameter> {
        &self.exposed_parameters
    }

    /// Return nodes in stable authoring-identity order.
    #[must_use]
    pub const fn nodes(&self) -> &BTreeMap<NodeId, NodeDefinition> {
        &self.nodes
    }

    /// Return named graph outputs in canonical name order.
    #[must_use]
    pub const fn outputs(&self) -> &BTreeMap<GraphName, NodeOutput> {
        &self.outputs
    }

    /// Return graph-level opaque records in preserved order.
    #[must_use]
    pub const fn unknown_records(&self) -> &[UnknownRecord] {
        &self.unknown_records
    }

    /// Return authoring-only metadata.
    #[must_use]
    pub const fn authoring(&self) -> &GraphAuthoring {
        &self.authoring
    }

    /// Replace authoring-only metadata without changing computational identity.
    #[must_use]
    pub fn with_authoring(mut self, authoring: GraphAuthoring) -> Self {
        self.authoring = authoring;
        self
    }

    pub(crate) fn records_clone(&self) -> GraphRecords {
        GraphRecords {
            inputs: self.inputs.clone(),
            exposed_parameters: self.exposed_parameters.clone(),
            nodes: self.nodes.clone(),
            outputs: self.outputs.clone(),
            unknown_records: self.unknown_records.clone(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn graph_names_and_unknown_record_kinds_are_validated() {
        assert_eq!(
            GraphName::new("source_image").map(|name| name.to_string()),
            Ok("source_image".into())
        );
        assert_eq!(GraphName::new("Source Image"), Err(DefinitionError::InvalidName));
        assert_eq!(
            UnknownRecord::new("  ", Box::<[u8]>::default()),
            Err(DefinitionError::InvalidUnknownRecordKind)
        );
    }

    #[test]
    fn authoring_metadata_does_not_change_computational_identity() {
        let schema = GraphSchemaVersion::new(1)
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"));
        let revision = GraphRevisionId::new(1)
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"));
        let original = GraphDefinition::new(
            schema,
            revision,
            GraphRecords::default(),
            GraphAuthoring::default(),
        );
        let relabeled = original.clone().with_authoring(GraphAuthoring {
            label: Some("Visible label".into()),
            annotations: BTreeMap::from([("layout".into(), "expanded".into())]),
        });

        assert_eq!(original.content_id(), relabeled.content_id());
        assert_ne!(original.authoring(), relabeled.authoring());
    }
}
