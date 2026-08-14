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

//! Responsibility: Compile valid graph outputs into a deterministic minimal dependency plan.
//!
//! Does not own: kernel selection, operation execution, scheduling, caches, or retained products.

use std::collections::{BTreeMap, BTreeSet};
use std::fmt;

use ferrastra_core::{CapabilitySet, Diagnostic, DiagnosticError};

use crate::{
    GraphContentId, GraphDefinition, GraphName, InputBinding, NodeDefinition, NodeId, NodeOutput,
    OperationCatalog, validate_graph,
};

/// Error returned without publishing a partial compiled plan.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CompileError {
    /// The graph failed typed structural validation.
    Validation(Box<[Diagnostic]>),
    /// An internal stable diagnostic declaration was invalid.
    Diagnostic(DiagnosticError),
}

impl fmt::Display for CompileError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Validation(_) => formatter.write_str("graph failed validation"),
            Self::Diagnostic(error) => error.fmt(formatter),
        }
    }
}

impl std::error::Error for CompileError {}

/// One reachable operation node in dependency-first execution order.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompiledNode {
    /// Stable authoring identity retained for diagnostics and patches.
    pub node: NodeId,
    /// Complete immutable normalized node definition.
    pub definition: NodeDefinition,
    /// Direct reachable node dependencies in stable identity order.
    pub dependencies: Box<[NodeId]>,
}

/// Immutable minimal plan containing only nodes reachable from named outputs.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompiledPlan {
    graph_content_id: GraphContentId,
    nodes: Box<[CompiledNode]>,
    outputs: BTreeMap<GraphName, NodeOutput>,
}

impl CompiledPlan {
    /// Return the normalized graph identity compiled into this plan.
    #[must_use]
    pub const fn graph_content_id(&self) -> GraphContentId {
        self.graph_content_id
    }

    /// Return reachable nodes in deterministic dependency-first order.
    #[must_use]
    pub const fn nodes(&self) -> &[CompiledNode] {
        &self.nodes
    }

    /// Return the named output bindings.
    #[must_use]
    pub const fn outputs(&self) -> &BTreeMap<GraphName, NodeOutput> {
        &self.outputs
    }
}

/// Validate and compile a graph into a deterministic dependency-first minimal plan.
///
/// # Errors
///
/// Returns [`CompileError`] when graph validation fails.
pub fn compile_graph(
    graph: &GraphDefinition,
    catalog: &impl OperationCatalog,
    available_capabilities: &CapabilitySet,
) -> Result<CompiledPlan, CompileError> {
    let report =
        validate_graph(graph, catalog, available_capabilities).map_err(CompileError::Diagnostic)?;
    if !report.valid {
        return Err(CompileError::Validation(report.diagnostics));
    }

    let reachable = reachable_nodes(graph);
    let mut remaining_dependencies = BTreeMap::new();
    let mut dependants: BTreeMap<NodeId, BTreeSet<NodeId>> = BTreeMap::new();
    for node_id in &reachable {
        let dependencies = dependencies(graph.nodes().get(node_id), &reachable);
        for dependency in &dependencies {
            dependants.entry(*dependency).or_default().insert(*node_id);
        }
        remaining_dependencies.insert(*node_id, dependencies);
    }

    let mut ready = remaining_dependencies
        .iter()
        .filter_map(|(node, dependencies)| dependencies.is_empty().then_some(*node))
        .collect::<BTreeSet<_>>();
    let mut compiled = Vec::with_capacity(reachable.len());
    while let Some(node_id) = ready.pop_first() {
        let Some(definition) = graph.nodes().get(&node_id) else {
            continue;
        };
        let direct_dependencies = dependencies(Some(definition), &reachable);
        compiled.push(CompiledNode {
            node: node_id,
            definition: definition.clone(),
            dependencies: direct_dependencies.iter().copied().collect(),
        });
        if let Some(children) = dependants.get(&node_id) {
            for child in children {
                if let Some(pending) = remaining_dependencies.get_mut(child) {
                    pending.remove(&node_id);
                    if pending.is_empty() {
                        ready.insert(*child);
                    }
                }
            }
        }
    }
    Ok(CompiledPlan {
        graph_content_id: graph.content_id(),
        nodes: compiled.into_boxed_slice(),
        outputs: graph.outputs().clone(),
    })
}

fn reachable_nodes(graph: &GraphDefinition) -> BTreeSet<NodeId> {
    let mut reachable = BTreeSet::new();
    let mut pending = graph.outputs().values().map(|output| output.node).collect::<Vec<_>>();
    while let Some(node_id) = pending.pop() {
        if !reachable.insert(node_id) {
            continue;
        }
        if let Some(node) = graph.nodes().get(&node_id) {
            pending.extend(node.inputs.values().filter_map(|binding| match binding {
                InputBinding::Node(output) => Some(output.node),
                InputBinding::GraphInput(_) => None,
            }));
        }
    }
    reachable
}

fn dependencies(node: Option<&NodeDefinition>, reachable: &BTreeSet<NodeId>) -> BTreeSet<NodeId> {
    node.into_iter()
        .flat_map(|definition| definition.inputs.values())
        .filter_map(|binding| match binding {
            InputBinding::Node(output) if reachable.contains(&output.node) => Some(output.node),
            InputBinding::GraphInput(_) | InputBinding::Node(_) => None,
        })
        .collect()
}
