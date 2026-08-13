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

//! Responsibility: Reconstruct typed immutable graph records from private canonical wire records.
//!
//! Does not own: JSON parsing, catalog validation, compilation, operation resolution, or migrations.

use std::collections::BTreeMap;

use ferrastra_core::{
    ContentId, CoverageFormat, FiniteScalar, OperationIdentity, ParameterId, ParameterType,
    ParameterValue, PortId, ProductKind, ProductSpec, RasterFormat, SemanticOperationId,
    SemanticVersion, Unit,
};

use crate::wire::{
    AuthoringWire, ExposedParameterWire, GraphWire, InputBindingWire, NodeOutputWire, NodeWire,
    ParameterBindingWire, ParameterTypeWire, ParameterValueWire, ProductFormatWire,
    ProductKindWire, ProductWire, UnitWire, UnknownRecordWire,
};
use crate::{
    ExposedParameter, GraphAuthoring, GraphCodecError, GraphContentId, GraphDefinition, GraphName,
    GraphRecords, GraphRevisionId, GraphSchemaVersion, InputBinding, NodeAuthoring, NodeDefinition,
    NodeId, NodeOutput, ParameterBinding, UnknownRecord,
};

pub(crate) fn graph(wire: GraphWire) -> Result<GraphDefinition, GraphCodecError> {
    let expected_content = wire
        .content_id
        .parse::<ContentId>()
        .map(GraphContentId::from_content_id)
        .map_err(GraphCodecError::invalid)?;
    let schema_version =
        GraphSchemaVersion::new(wire.schema_version).map_err(GraphCodecError::invalid)?;
    let revision_id = GraphRevisionId::new(wire.revision_id).map_err(GraphCodecError::invalid)?;

    let mut inputs = BTreeMap::new();
    for item in wire.inputs {
        insert_unique(
            &mut inputs,
            GraphName::new(item.name).map_err(GraphCodecError::invalid)?,
            product(item.product)?,
        )?;
    }
    let mut exposed_parameters = BTreeMap::new();
    for item in wire.exposed_parameters {
        insert_unique(
            &mut exposed_parameters,
            GraphName::new(item.name).map_err(GraphCodecError::invalid)?,
            exposed_parameter(item.parameter)?,
        )?;
    }
    let mut nodes = BTreeMap::new();
    for item in wire.nodes {
        let node_id = NodeId::new(item.id).map_err(GraphCodecError::invalid)?;
        insert_unique(&mut nodes, node_id, node(item)?)?;
    }
    let mut outputs = BTreeMap::new();
    for item in wire.outputs {
        insert_unique(
            &mut outputs,
            GraphName::new(item.name).map_err(GraphCodecError::invalid)?,
            node_output(item.output)?,
        )?;
    }
    let graph = GraphDefinition::new(
        schema_version,
        revision_id,
        GraphRecords {
            inputs,
            exposed_parameters,
            nodes,
            outputs,
            unknown_records: unknown_records(wire.unknown_records)?,
        },
        graph_authoring(wire.authoring),
    );
    if graph.content_id() != expected_content {
        return Err(GraphCodecError::ContentIdentityMismatch);
    }
    Ok(graph)
}

fn node(wire: NodeWire) -> Result<NodeDefinition, GraphCodecError> {
    let operation = OperationIdentity::new(
        SemanticOperationId::new(wire.operation_id).map_err(GraphCodecError::invalid)?,
        SemanticVersion::new(wire.operation_version).map_err(GraphCodecError::invalid)?,
    );
    let mut parameters = BTreeMap::new();
    for item in wire.parameters {
        let parameter = ParameterId::new(item.parameter).map_err(GraphCodecError::invalid)?;
        let binding = match item.binding {
            ParameterBindingWire::Constant(value) => {
                ParameterBinding::Constant(parameter_value(value)?)
            }
            ParameterBindingWire::Exposed(name) => {
                ParameterBinding::Exposed(GraphName::new(name).map_err(GraphCodecError::invalid)?)
            }
        };
        insert_unique(&mut parameters, parameter, binding)?;
    }
    let mut inputs = BTreeMap::new();
    for item in wire.inputs {
        let port = PortId::new(item.port).map_err(GraphCodecError::invalid)?;
        let binding = match item.binding {
            InputBindingWire::GraphInput(name) => {
                InputBinding::GraphInput(GraphName::new(name).map_err(GraphCodecError::invalid)?)
            }
            InputBindingWire::Node(output) => InputBinding::Node(node_output(output)?),
        };
        insert_unique(&mut inputs, port, binding)?;
    }
    let source_revision = wire
        .source_revision
        .map(|value| value.parse::<ContentId>().map_err(GraphCodecError::invalid))
        .transpose()?;
    Ok(NodeDefinition {
        operation,
        parameters,
        inputs,
        source_revision,
        unknown_records: unknown_records(wire.unknown_records)?,
        authoring: node_authoring(wire.authoring),
    })
}

fn exposed_parameter(wire: ExposedParameterWire) -> Result<ExposedParameter, GraphCodecError> {
    Ok(ExposedParameter {
        node: NodeId::new(wire.node).map_err(GraphCodecError::invalid)?,
        parameter: ParameterId::new(wire.parameter).map_err(GraphCodecError::invalid)?,
        parameter_type: parameter_type(wire.parameter_type),
        unit: unit(wire.unit),
        default: parameter_value(wire.default)?,
    })
}

fn product(wire: ProductWire) -> Result<ProductSpec, GraphCodecError> {
    match (wire.kind, wire.format) {
        (ProductKindWire::Raster, Some(ProductFormatWire::Rgba8PremultipliedEncoded)) => {
            Ok(ProductSpec::raster(RasterFormat::Rgba8PremultipliedEncoded))
        }
        (ProductKindWire::Raster, Some(ProductFormatWire::Rgba16PremultipliedLinear)) => {
            Ok(ProductSpec::raster(RasterFormat::Rgba16PremultipliedLinear))
        }
        (ProductKindWire::Raster, Some(ProductFormatWire::Rgba32FloatPremultipliedLinear)) => {
            Ok(ProductSpec::raster(RasterFormat::Rgba32FloatPremultipliedLinear))
        }
        (ProductKindWire::Coverage, Some(ProductFormatWire::Coverage8)) => {
            Ok(ProductSpec::coverage(CoverageFormat::Coverage8))
        }
        (ProductKindWire::Coverage, Some(ProductFormatWire::Coverage16)) => {
            Ok(ProductSpec::coverage(CoverageFormat::Coverage16))
        }
        (ProductKindWire::Coverage, Some(ProductFormatWire::Coverage32Float)) => {
            Ok(ProductSpec::coverage(CoverageFormat::Coverage32Float))
        }
        (kind, None) => {
            ProductSpec::abstract_product(product_kind(kind)).map_err(GraphCodecError::invalid)
        }
        _ => Err(GraphCodecError::InvalidRecord("product kind and format disagree".into())),
    }
}

fn product_kind(wire: ProductKindWire) -> ProductKind {
    match wire {
        ProductKindWire::Raster => ProductKind::Raster,
        ProductKindWire::Coverage => ProductKind::Coverage,
        ProductKindWire::Vector => ProductKind::Vector,
        ProductKindWire::Graphic => ProductKind::Graphic,
        ProductKindWire::Scalar => ProductKind::Scalar,
        ProductKindWire::Color => ProductKind::Color,
        ProductKindWire::Transform => ProductKind::Transform,
        ProductKindWire::Metadata => ProductKind::Metadata,
    }
}

fn parameter_value(wire: ParameterValueWire) -> Result<ParameterValue, GraphCodecError> {
    match wire {
        ParameterValueWire::Boolean(value) => Ok(ParameterValue::Boolean(value)),
        ParameterValueWire::Integer(value) => Ok(ParameterValue::Integer(value)),
        ParameterValueWire::ScalarBits(bits) => FiniteScalar::new(f64::from_bits(bits))
            .map(ParameterValue::Scalar)
            .map_err(GraphCodecError::invalid),
        ParameterValueWire::Text(value) => Ok(ParameterValue::Text(value.into())),
        ParameterValueWire::Enum(value) => {
            ParameterId::new(value).map(ParameterValue::Enum).map_err(GraphCodecError::invalid)
        }
    }
}

fn parameter_type(wire: ParameterTypeWire) -> ParameterType {
    match wire {
        ParameterTypeWire::Boolean => ParameterType::Boolean,
        ParameterTypeWire::Integer => ParameterType::Integer,
        ParameterTypeWire::Scalar => ParameterType::Scalar,
        ParameterTypeWire::Text => ParameterType::Text,
        ParameterTypeWire::Enum => ParameterType::Enum,
    }
}

fn unit(wire: UnitWire) -> Unit {
    match wire {
        UnitWire::Unitless => Unit::Unitless,
        UnitWire::Pixels => Unit::Pixels,
        UnitWire::Degrees => Unit::Degrees,
        UnitWire::Ratio => Unit::Ratio,
        UnitWire::Percent => Unit::Percent,
    }
}

fn node_output(wire: NodeOutputWire) -> Result<NodeOutput, GraphCodecError> {
    Ok(NodeOutput {
        node: NodeId::new(wire.node).map_err(GraphCodecError::invalid)?,
        port: PortId::new(wire.port).map_err(GraphCodecError::invalid)?,
    })
}

fn unknown_records(
    records: Vec<UnknownRecordWire>,
) -> Result<Box<[UnknownRecord]>, GraphCodecError> {
    records
        .into_iter()
        .map(|record| {
            UnknownRecord::new(record.kind, record.payload).map_err(GraphCodecError::invalid)
        })
        .collect::<Result<Vec<_>, _>>()
        .map(Vec::into_boxed_slice)
}

fn graph_authoring(wire: AuthoringWire) -> GraphAuthoring {
    GraphAuthoring {
        label: wire.label.map(String::into_boxed_str),
        annotations: string_map(wire.annotations),
    }
}

fn node_authoring(wire: AuthoringWire) -> NodeAuthoring {
    NodeAuthoring {
        label: wire.label.map(String::into_boxed_str),
        annotations: string_map(wire.annotations),
    }
}

fn string_map(values: BTreeMap<String, String>) -> BTreeMap<Box<str>, Box<str>> {
    values.into_iter().map(|(key, value)| (key.into_boxed_str(), value.into_boxed_str())).collect()
}

fn insert_unique<K: Ord, V>(
    values: &mut BTreeMap<K, V>,
    key: K,
    value: V,
) -> Result<(), GraphCodecError> {
    if values.insert(key, value).is_some() {
        return Err(GraphCodecError::InvalidRecord(
            "canonical graph contains a duplicate stable key".into(),
        ));
    }
    Ok(())
}
