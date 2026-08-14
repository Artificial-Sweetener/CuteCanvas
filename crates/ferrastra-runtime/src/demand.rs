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

//! Responsibility: Propagate exact named regional demand backward through a compiled plan.
//!
//! Does not own: operation demand rules, graph compilation, scheduling, source lookup, or execution.

use std::collections::BTreeMap;

use ferrastra_core::{IntRect, OperationRequest, PortDirection, PortId, ProductSpec, QualityTier};
use ferrastra_graph::{CompiledPlan, GraphName, InputBinding, NodeId, NodeOutput};

use crate::{EvaluationError, OperationSet};

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct NodeDemand {
    pub(crate) output_port: PortId,
    pub(crate) region: IntRect,
    pub(crate) product: ProductSpec,
}

pub(crate) fn plan(
    compiled: &CompiledPlan,
    output_name: &GraphName,
    output_region: IntRect,
    quality: QualityTier,
    operations: &OperationSet,
) -> Result<BTreeMap<NodeId, NodeDemand>, EvaluationError> {
    let output = compiled.outputs().get(output_name).ok_or(EvaluationError::UnknownOutput)?;
    let output_product = product_for_output(compiled, output, operations)?;
    let mut demands = BTreeMap::from([(
        output.node,
        NodeDemand {
            output_port: output.port.clone(),
            region: output_region,
            product: output_product,
        },
    )]);

    for compiled_node in compiled.nodes().iter().rev() {
        let Some(node_demand) = demands.get(&compiled_node.node).cloned() else {
            continue;
        };
        let operation = operations
            .operation(&compiled_node.definition.operation)
            .ok_or(EvaluationError::MissingOperation)?;
        let request = OperationRequest {
            output_region: node_demand.region,
            output: node_demand.product,
            quality,
            parameters: crate::parameters::resolve(
                &compiled_node.definition,
                operation.descriptor(),
            )?,
        };
        let upstream = operation.backward_demand(&request)?;
        for input_demand in upstream {
            let binding = compiled_node
                .definition
                .inputs
                .get(&input_demand.port)
                .ok_or(EvaluationError::ConflictingDemand)?;
            let InputBinding::Node(source) = binding else {
                return Err(EvaluationError::GraphInputUnsupported);
            };
            let product = product_for_output(compiled, source, operations)?;
            merge(
                &mut demands,
                source.node,
                NodeDemand {
                    output_port: source.port.clone(),
                    region: input_demand.region,
                    product,
                },
            )?;
        }
    }
    Ok(demands)
}

fn product_for_output(
    compiled: &CompiledPlan,
    output: &NodeOutput,
    operations: &OperationSet,
) -> Result<ProductSpec, EvaluationError> {
    let node = compiled
        .nodes()
        .iter()
        .find(|node| node.node == output.node)
        .ok_or(EvaluationError::MissingOperation)?;
    let operation = operations
        .operation(&node.definition.operation)
        .ok_or(EvaluationError::MissingOperation)?;
    operation
        .descriptor()
        .ports
        .iter()
        .find(|port| port.direction == PortDirection::Output && port.id == output.port)
        .map(|port| port.product)
        .ok_or(EvaluationError::MissingOperation)
}

fn merge(
    demands: &mut BTreeMap<NodeId, NodeDemand>,
    node: NodeId,
    requested: NodeDemand,
) -> Result<(), EvaluationError> {
    if let Some(existing) = demands.get_mut(&node) {
        if existing.output_port != requested.output_port || existing.product != requested.product {
            return Err(EvaluationError::ConflictingDemand);
        }
        existing.region = existing.region.union(requested.region)?;
    } else {
        demands.insert(node, requested);
    }
    Ok(())
}
