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

//! Responsibility: Validate typed graph structure against operation descriptors and capabilities.
//!
//! Does not own: operation registration, graph mutation, source availability, planning, or execution.

use std::collections::{BTreeMap, BTreeSet};

use ferrastra_core::{
    CapabilitySet, Diagnostic, DiagnosticCode, DiagnosticError, DiagnosticSeverity,
    DiagnosticTarget, OperationDescriptor, OperationIdentity, PortDescriptor, PortDirection,
    ProductSpec,
};

use crate::{GraphDefinition, InputBinding, NodeDefinition, NodeId, NodeOutput, ParameterBinding};

/// Read-only descriptor source supplied to graph validation and compilation.
pub trait OperationCatalog {
    /// Return the exact descriptor for one semantic operation version.
    fn descriptor(&self, identity: &OperationIdentity) -> Option<&OperationDescriptor>;
}

impl OperationCatalog for BTreeMap<OperationIdentity, OperationDescriptor> {
    fn descriptor(&self, identity: &OperationIdentity) -> Option<&OperationDescriptor> {
        self.get(identity)
    }
}

/// Stable structured result of graph validation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ValidationReport {
    /// Whether no error-severity diagnostics were produced.
    pub valid: bool,
    /// Deterministically ordered validation diagnostics.
    pub diagnostics: Box<[Diagnostic]>,
}

/// Validate an immutable graph without modifying or partially compiling it.
///
/// # Errors
///
/// Returns [`DiagnosticError`] only if an internal stable diagnostic declaration is invalid.
pub fn validate_graph(
    graph: &GraphDefinition,
    catalog: &impl OperationCatalog,
    available_capabilities: &CapabilitySet,
) -> Result<ValidationReport, DiagnosticError> {
    let mut validator =
        Validator { graph, catalog, available_capabilities, diagnostics: Vec::new() };
    validator.validate_nodes()?;
    validator.validate_outputs()?;
    validator.validate_cycles()?;
    let valid = validator.diagnostics.iter().all(|item| !item.is_error());
    Ok(ValidationReport { valid, diagnostics: validator.diagnostics.into_boxed_slice() })
}

struct Validator<'a, C> {
    graph: &'a GraphDefinition,
    catalog: &'a C,
    available_capabilities: &'a CapabilitySet,
    diagnostics: Vec<Diagnostic>,
}

impl<C: OperationCatalog> Validator<'_, C> {
    fn validate_nodes(&mut self) -> Result<(), DiagnosticError> {
        for (node_id, node) in self.graph.nodes() {
            let Some(descriptor) = self.catalog.descriptor(&node.operation) else {
                self.push(
                    "UNKNOWN_OPERATION",
                    target(*node_id, node, None),
                    "The requested operation semantic version is unavailable.",
                )?;
                continue;
            };
            if descriptor.validate().is_err() {
                self.push(
                    "INVALID_OPERATION_DESCRIPTOR",
                    target(*node_id, node, None),
                    "The operation descriptor is incomplete or contradictory.",
                )?;
                continue;
            }
            if !descriptor.computation.required_capabilities.is_subset(self.available_capabilities)
            {
                self.push(
                    "MISSING_CAPABILITY",
                    target(*node_id, node, None),
                    "The selected execution contract lacks a required capability.",
                )?;
            }
            self.validate_parameters(*node_id, node, descriptor)?;
            self.validate_inputs(*node_id, node, descriptor)?;
        }
        Ok(())
    }

    fn validate_parameters(
        &mut self,
        node_id: NodeId,
        node: &NodeDefinition,
        descriptor: &OperationDescriptor,
    ) -> Result<(), DiagnosticError> {
        for (parameter_id, binding) in &node.parameters {
            let Some(parameter) =
                descriptor.parameters.iter().find(|candidate| candidate.id == *parameter_id)
            else {
                let mut diagnostic_target = target(node_id, node, None);
                diagnostic_target.parameter = Some(parameter_id.clone());
                self.push(
                    "UNKNOWN_PARAMETER",
                    diagnostic_target,
                    "The node binds a parameter absent from its operation descriptor.",
                )?;
                continue;
            };
            let valid = match binding {
                ParameterBinding::Constant(value) => parameter.validate_value(value).is_ok(),
                ParameterBinding::Exposed(name) => {
                    self.graph.exposed_parameters().get(name).is_some_and(|exposed| {
                        exposed.node == node_id
                            && exposed.parameter == *parameter_id
                            && exposed.parameter_type == parameter.parameter_type
                            && exposed.unit == parameter.unit
                            && parameter.validate_value(&exposed.default).is_ok()
                    })
                }
            };
            if !valid {
                let mut diagnostic_target = target(node_id, node, None);
                diagnostic_target.parameter = Some(parameter_id.clone());
                self.push(
                    "INVALID_PARAMETER_BINDING",
                    diagnostic_target,
                    "The parameter binding violates its declared type, unit, range, or target.",
                )?;
            }
        }
        Ok(())
    }

    fn validate_inputs(
        &mut self,
        node_id: NodeId,
        node: &NodeDefinition,
        descriptor: &OperationDescriptor,
    ) -> Result<(), DiagnosticError> {
        for (port_id, binding) in &node.inputs {
            let Some(port) = input_port(descriptor, port_id) else {
                self.push(
                    "UNKNOWN_INPUT_PORT",
                    target(node_id, node, Some(port_id.clone())),
                    "The node binds an input absent from its operation descriptor.",
                )?;
                continue;
            };
            let supplied = self.binding_product(binding);
            if supplied != Some(port.product) {
                self.push(
                    "INPUT_TYPE_MISMATCH",
                    target(node_id, node, Some(port_id.clone())),
                    "The connected product does not match the input port contract.",
                )?;
            }
        }
        for port in descriptor
            .ports
            .iter()
            .filter(|port| port.direction == PortDirection::Input && port.required)
        {
            if !node.inputs.contains_key(&port.id) {
                self.push(
                    "MISSING_REQUIRED_INPUT",
                    target(node_id, node, Some(port.id.clone())),
                    "A required operation input is not connected.",
                )?;
            }
        }
        Ok(())
    }

    fn binding_product(&self, binding: &InputBinding) -> Option<ProductSpec> {
        match binding {
            InputBinding::GraphInput(name) => self.graph.inputs().get(name).copied(),
            InputBinding::Node(output) => self.output_product(output),
        }
    }

    fn output_product(&self, output: &NodeOutput) -> Option<ProductSpec> {
        let node = self.graph.nodes().get(&output.node)?;
        let descriptor = self.catalog.descriptor(&node.operation)?;
        descriptor
            .ports
            .iter()
            .find(|port| port.direction == PortDirection::Output && port.id == output.port)
            .map(|port| port.product)
    }

    fn validate_outputs(&mut self) -> Result<(), DiagnosticError> {
        for output in self.graph.outputs().values() {
            if self.output_product(output).is_none() {
                let node = self.graph.nodes().get(&output.node);
                self.push(
                    "INVALID_GRAPH_OUTPUT",
                    DiagnosticTarget {
                        operation: node.map(|item| item.operation.semantic_id().clone()),
                        node: Some(output.node.to_string().into()),
                        port: Some(output.port.clone()),
                        parameter: None,
                    },
                    "A graph output references a missing node or output port.",
                )?;
            }
        }
        Ok(())
    }

    fn validate_cycles(&mut self) -> Result<(), DiagnosticError> {
        let mut remaining_dependencies = BTreeMap::new();
        let mut dependants: BTreeMap<NodeId, Vec<NodeId>> = BTreeMap::new();
        for (node_id, node) in self.graph.nodes() {
            let dependencies = node
                .inputs
                .values()
                .filter_map(|binding| match binding {
                    InputBinding::Node(output) if self.graph.nodes().contains_key(&output.node) => {
                        Some(output.node)
                    }
                    InputBinding::GraphInput(_) | InputBinding::Node(_) => None,
                })
                .collect::<BTreeSet<_>>();
            for dependency in &dependencies {
                dependants.entry(*dependency).or_default().push(*node_id);
            }
            remaining_dependencies.insert(*node_id, dependencies.len());
        }
        let mut ready = remaining_dependencies
            .iter()
            .filter_map(|(node, count)| (*count == 0).then_some(*node))
            .collect::<Vec<_>>();
        let mut visited = 0_usize;
        while let Some(node) = ready.pop() {
            visited += 1;
            if let Some(children) = dependants.get(&node) {
                for child in children {
                    if let Some(count) = remaining_dependencies.get_mut(child) {
                        *count = count.saturating_sub(1);
                        if *count == 0 {
                            ready.push(*child);
                        }
                    }
                }
            }
        }
        if visited != self.graph.nodes().len() {
            self.push(
                "GRAPH_CYCLE",
                DiagnosticTarget::default(),
                "The graph contains a dependency cycle.",
            )?;
        }
        Ok(())
    }

    fn push(
        &mut self,
        code: &str,
        diagnostic_target: DiagnosticTarget,
        message: &str,
    ) -> Result<(), DiagnosticError> {
        self.diagnostics.push(Diagnostic::new(
            DiagnosticCode::new(code)?,
            DiagnosticSeverity::Error,
            diagnostic_target,
            message,
        )?);
        Ok(())
    }
}

fn input_port<'a>(
    descriptor: &'a OperationDescriptor,
    id: &ferrastra_core::PortId,
) -> Option<&'a PortDescriptor> {
    descriptor.ports.iter().find(|port| port.direction == PortDirection::Input && port.id == *id)
}

fn target(
    node_id: NodeId,
    node: &NodeDefinition,
    port: Option<ferrastra_core::PortId>,
) -> DiagnosticTarget {
    DiagnosticTarget {
        operation: Some(node.operation.semantic_id().clone()),
        node: Some(node_id.to_string().into()),
        port,
        parameter: None,
    }
}
