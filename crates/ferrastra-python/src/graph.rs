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

//! Responsibility: Expose typed Python graph construction and canonical serialization handles.
//!
//! Does not own: graph semantics, validation, compilation, evaluation, or operation algorithms.

use std::collections::BTreeMap;
use std::str::FromStr;

use ferrastra_core::{
    ContentId, FiniteScalar, OperationIdentity, ParameterId, ParameterValue, PortId,
    SemanticOperationId, SemanticVersion,
};
use ferrastra_graph::{
    GraphAuthoring, GraphBuilder, GraphDefinition, GraphName, GraphRevisionId, GraphSchemaVersion,
    NodeId, NodeOutput, deserialize_graph, serialize_graph,
};
use pyo3::prelude::*;

use crate::errors;

/// Immutable Python handle to one canonical graph revision.
#[pyclass(name = "Graph", module = "ferrastra._native", frozen, skip_from_py_object)]
#[derive(Clone)]
pub(crate) struct PyGraph {
    inner: GraphDefinition,
}

#[pymethods]
impl PyGraph {
    /// Decode and verify one canonical serialized graph.
    #[staticmethod]
    fn from_json(serialized: &str) -> PyResult<Self> {
        deserialize_graph(serialized.as_bytes()).map(|inner| Self { inner }).map_err(errors::graph)
    }

    /// Return canonical deterministic JSON.
    fn to_json(&self) -> PyResult<String> {
        let encoded = serialize_graph(&self.inner).map_err(errors::graph)?;
        String::from_utf8(encoded.into_vec()).map_err(errors::graph)
    }

    /// Return the normalized computational graph identity.
    #[getter]
    fn content_id(&self) -> String {
        self.inner.content_id().to_string()
    }

    /// Return the author-assigned graph revision number.
    #[getter]
    fn revision_id(&self) -> u64 {
        self.inner.revision_id().get()
    }

    /// Return the canonical graph schema version.
    #[getter]
    fn schema_version(&self) -> u32 {
        self.inner.schema_version().get()
    }
}

impl PyGraph {
    pub(crate) const fn inner(&self) -> &GraphDefinition {
        &self.inner
    }
}

/// Mutable Python construction surface that publishes immutable graph snapshots.
#[pyclass(name = "GraphBuilder", module = "ferrastra._native")]
pub(crate) struct PyGraphBuilder {
    inner: GraphBuilder,
}

#[pymethods]
impl PyGraphBuilder {
    /// Begin one graph revision using the canonical schema by default.
    #[new]
    #[pyo3(signature = (revision_id, *, schema_version = 1))]
    fn new(revision_id: u64, schema_version: u32) -> PyResult<Self> {
        let schema_version = GraphSchemaVersion::new(schema_version).map_err(errors::graph)?;
        let revision_id = GraphRevisionId::new(revision_id).map_err(errors::graph)?;
        Ok(Self { inner: GraphBuilder::new(schema_version, revision_id) })
    }

    /// Add one stable node with explicit operation semantics.
    #[pyo3(signature = (node_id, operation_id, *, semantic_version = 1))]
    fn add_node(
        &mut self,
        node_id: u64,
        operation_id: &str,
        semantic_version: u32,
    ) -> PyResult<()> {
        self.inner
            .add_node(node(node_id)?, operation(operation_id, semantic_version)?)
            .map_err(errors::graph)
    }

    /// Bind a canonical immutable source revision to one source node.
    fn set_source_revision(&mut self, node_id: u64, revision: &str) -> PyResult<()> {
        self.inner
            .set_source_revision(
                node(node_id)?,
                ContentId::from_str(revision).map_err(errors::graph)?,
            )
            .map_err(errors::graph)
    }

    /// Connect one named node output to one named input port.
    fn connect(
        &mut self,
        source_node: u64,
        source_port: &str,
        destination_node: u64,
        destination_port: &str,
    ) -> PyResult<()> {
        self.inner
            .connect(
                NodeOutput { node: node(source_node)?, port: port(source_port)? },
                node(destination_node)?,
                port(destination_port)?,
            )
            .map_err(errors::graph)
    }

    /// Publish one named graph output.
    #[pyo3(signature = (name, node_id, *, port_name = "result"))]
    fn add_output(&mut self, name: &str, node_id: u64, port_name: &str) -> PyResult<()> {
        self.inner
            .add_output(
                graph_name(name)?,
                NodeOutput { node: node(node_id)?, port: port(port_name)? },
            )
            .map_err(errors::graph)
    }

    /// Set a canonical Boolean operation parameter.
    fn set_boolean(&mut self, node_id: u64, parameter: &str, value: bool) -> PyResult<()> {
        self.set_parameter(node_id, parameter, ParameterValue::Boolean(value))
    }

    /// Set a canonical signed-integer operation parameter.
    fn set_integer(&mut self, node_id: u64, parameter: &str, value: i64) -> PyResult<()> {
        self.set_parameter(node_id, parameter, ParameterValue::Integer(value))
    }

    /// Set a canonical finite-scalar operation parameter.
    fn set_scalar(&mut self, node_id: u64, parameter: &str, value: f64) -> PyResult<()> {
        let value = FiniteScalar::new(value).map_err(errors::graph)?;
        self.set_parameter(node_id, parameter, ParameterValue::Scalar(value))
    }

    /// Set a canonical text operation parameter.
    fn set_text(&mut self, node_id: u64, parameter: &str, value: &str) -> PyResult<()> {
        self.set_parameter(node_id, parameter, ParameterValue::Text(value.into()))
    }

    /// Set a canonical enum-case operation parameter.
    fn set_enum(&mut self, node_id: u64, parameter: &str, value: &str) -> PyResult<()> {
        let value = ParameterId::new(value).map_err(errors::graph)?;
        self.set_parameter(node_id, parameter, ParameterValue::Enum(value))
    }

    /// Set graph-level authoring metadata excluded from computational identity.
    fn set_label(&mut self, label: Option<&str>) {
        self.inner.set_authoring(GraphAuthoring {
            label: label.map(Into::into),
            annotations: BTreeMap::new(),
        });
    }

    /// Publish an immutable graph snapshot while keeping this builder reusable.
    fn build(&self) -> PyGraph {
        PyGraph { inner: self.inner.clone().build() }
    }
}

impl PyGraphBuilder {
    fn set_parameter(
        &mut self,
        node_id: u64,
        parameter: &str,
        value: ParameterValue,
    ) -> PyResult<()> {
        self.inner
            .set_parameter(
                node(node_id)?,
                ParameterId::new(parameter).map_err(errors::graph)?,
                value,
            )
            .map_err(errors::graph)
    }
}

fn node(value: u64) -> PyResult<NodeId> {
    NodeId::new(value).map_err(errors::graph)
}

fn port(value: &str) -> PyResult<PortId> {
    PortId::new(value).map_err(errors::graph)
}

pub(crate) fn graph_name(value: &str) -> PyResult<GraphName> {
    GraphName::new(value).map_err(errors::graph)
}

fn operation(value: &str, version: u32) -> PyResult<OperationIdentity> {
    Ok(OperationIdentity::new(
        SemanticOperationId::new(value).map_err(errors::graph)?,
        SemanticVersion::new(version).map_err(errors::graph)?,
    ))
}
