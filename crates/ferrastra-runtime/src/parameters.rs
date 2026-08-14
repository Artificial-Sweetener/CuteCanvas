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

//! Responsibility: Resolve descriptor defaults and constant graph bindings for one invocation.
//!
//! Does not own: parameter schemas, exposed-parameter caller values, graph validation, or caching.

use std::collections::BTreeMap;

use ferrastra_core::{OperationDescriptor, OperationParameters};
use ferrastra_graph::{NodeDefinition, ParameterBinding};

use crate::EvaluationError;

pub(crate) fn resolve(
    node: &NodeDefinition,
    descriptor: &OperationDescriptor,
) -> Result<OperationParameters, EvaluationError> {
    let mut values = descriptor
        .parameters
        .iter()
        .map(|parameter| (parameter.id.clone(), parameter.default.clone()))
        .collect::<BTreeMap<_, _>>();
    for (parameter, binding) in &node.parameters {
        let ParameterBinding::Constant(value) = binding else {
            return Err(EvaluationError::GraphParameterUnsupported);
        };
        values.insert(parameter.clone(), value.clone());
    }
    Ok(OperationParameters::new(values))
}
