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

//! Responsibility: Propagate exact source damage forward through reachable compiled nodes.
//!
//! Does not own: operation damage rules, graph compilation, cache invalidation, or publication.

use std::collections::BTreeMap;

use ferrastra_core::{IntRect, OperationDamageRequest};
use ferrastra_graph::{CompiledPlan, InputBinding, NodeId};

use crate::{EvaluationError, OperationSet};

/// Propagate one changed source region to every affected reachable node.
///
/// # Errors
///
/// Returns [`EvaluationError`] when a required operation is unavailable or damage geometry fails.
pub fn propagate_damage(
    compiled: &CompiledPlan,
    source_node: NodeId,
    source_damage: IntRect,
    operations: &OperationSet,
) -> Result<BTreeMap<NodeId, IntRect>, EvaluationError> {
    let mut damage = BTreeMap::from([(source_node, source_damage)]);
    for node in compiled.nodes() {
        if node.node == source_node {
            continue;
        }
        let operation = operations
            .operation(&node.definition.operation)
            .ok_or(EvaluationError::MissingOperation)?;
        for (port, binding) in &node.definition.inputs {
            let InputBinding::Node(source) = binding else {
                continue;
            };
            let Some(input_damage) = damage.get(&source.node).copied() else {
                continue;
            };
            let output_damage = operation.forward_damage(&OperationDamageRequest {
                input: port.clone(),
                input_damage,
                parameters: crate::parameters::resolve(&node.definition, operation.descriptor())?,
            })?;
            if let Some(existing) = damage.get_mut(&node.node) {
                *existing = existing.union(output_damage)?;
            } else {
                damage.insert(node.node, output_damage);
            }
        }
    }
    Ok(damage)
}
