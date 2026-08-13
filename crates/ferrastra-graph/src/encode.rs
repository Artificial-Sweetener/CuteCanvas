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

//! Responsibility: Convert immutable typed graph records into canonical private wire records.
//!
//! Does not own: JSON encoding, decoding, graph validation, normalization, or public contracts.

use std::collections::BTreeMap;

use ferrastra_core::{
    CoverageFormat, ParameterType, ParameterValue, ProductFormat, ProductKind, ProductSpec,
    RasterFormat, Unit,
};

use crate::wire::{
    AuthoringWire, ExposedParameterWire, GraphWire, InputBindingWire, NamedExposedParameterWire,
    NamedInputBindingWire, NamedOutputWire, NamedParameterBindingWire, NamedProductWire,
    NodeOutputWire, NodeWire, ParameterBindingWire, ParameterTypeWire, ParameterValueWire,
    ProductFormatWire, ProductKindWire, ProductWire, UnitWire, UnknownRecordWire,
};
use crate::{GraphDefinition, InputBinding, NodeAuthoring, ParameterBinding, UnknownRecord};

pub(crate) fn wire_graph(graph: &GraphDefinition) -> GraphWire {
    GraphWire {
        schema_version: graph.schema_version().get(),
        revision_id: graph.revision_id().get(),
        content_id: graph.content_id().to_string(),
        inputs: graph
            .inputs()
            .iter()
            .map(|(name, product)| NamedProductWire {
                name: name.to_string(),
                product: product_wire(*product),
            })
            .collect(),
        exposed_parameters: graph
            .exposed_parameters()
            .iter()
            .map(|(name, parameter)| NamedExposedParameterWire {
                name: name.to_string(),
                parameter: ExposedParameterWire {
                    node: parameter.node.get(),
                    parameter: parameter.parameter.to_string(),
                    parameter_type: parameter_type_wire(parameter.parameter_type),
                    unit: unit_wire(parameter.unit),
                    default: parameter_value_wire(&parameter.default),
                },
            })
            .collect(),
        nodes: graph
            .nodes()
            .iter()
            .map(|(node_id, node)| NodeWire {
                id: node_id.get(),
                operation_id: node.operation.semantic_id().to_string(),
                operation_version: node.operation.semantic_version().get(),
                parameters: node
                    .parameters
                    .iter()
                    .map(|(parameter, binding)| NamedParameterBindingWire {
                        parameter: parameter.to_string(),
                        binding: match binding {
                            ParameterBinding::Constant(value) => {
                                ParameterBindingWire::Constant(parameter_value_wire(value))
                            }
                            ParameterBinding::Exposed(name) => {
                                ParameterBindingWire::Exposed(name.to_string())
                            }
                        },
                    })
                    .collect(),
                inputs: node
                    .inputs
                    .iter()
                    .map(|(port, binding)| NamedInputBindingWire {
                        port: port.to_string(),
                        binding: match binding {
                            InputBinding::GraphInput(name) => {
                                InputBindingWire::GraphInput(name.to_string())
                            }
                            InputBinding::Node(output) => InputBindingWire::Node(NodeOutputWire {
                                node: output.node.get(),
                                port: output.port.to_string(),
                            }),
                        },
                    })
                    .collect(),
                source_revision: node.source_revision.map(|revision| revision.to_string()),
                unknown_records: unknown_records_wire(&node.unknown_records),
                authoring: node_authoring_wire(&node.authoring),
            })
            .collect(),
        outputs: graph
            .outputs()
            .iter()
            .map(|(name, output)| NamedOutputWire {
                name: name.to_string(),
                output: NodeOutputWire { node: output.node.get(), port: output.port.to_string() },
            })
            .collect(),
        unknown_records: unknown_records_wire(graph.unknown_records()),
        authoring: AuthoringWire {
            label: graph.authoring().label.as_deref().map(str::to_owned),
            annotations: string_map(&graph.authoring().annotations),
        },
    }
}

fn product_wire(product: ProductSpec) -> ProductWire {
    ProductWire {
        kind: match product.kind() {
            ProductKind::Raster => ProductKindWire::Raster,
            ProductKind::Coverage => ProductKindWire::Coverage,
            ProductKind::Vector => ProductKindWire::Vector,
            ProductKind::Graphic => ProductKindWire::Graphic,
            ProductKind::Scalar => ProductKindWire::Scalar,
            ProductKind::Color => ProductKindWire::Color,
            ProductKind::Transform => ProductKindWire::Transform,
            ProductKind::Metadata => ProductKindWire::Metadata,
        },
        format: product.format().map(|format| match format {
            ProductFormat::Raster(RasterFormat::Rgba8PremultipliedEncoded) => {
                ProductFormatWire::Rgba8PremultipliedEncoded
            }
            ProductFormat::Raster(RasterFormat::Rgba16PremultipliedLinear) => {
                ProductFormatWire::Rgba16PremultipliedLinear
            }
            ProductFormat::Raster(RasterFormat::Rgba32FloatPremultipliedLinear) => {
                ProductFormatWire::Rgba32FloatPremultipliedLinear
            }
            ProductFormat::Coverage(CoverageFormat::Coverage8) => ProductFormatWire::Coverage8,
            ProductFormat::Coverage(CoverageFormat::Coverage16) => ProductFormatWire::Coverage16,
            ProductFormat::Coverage(CoverageFormat::Coverage32Float) => {
                ProductFormatWire::Coverage32Float
            }
        }),
    }
}

fn parameter_value_wire(value: &ParameterValue) -> ParameterValueWire {
    match value {
        ParameterValue::Boolean(value) => ParameterValueWire::Boolean(*value),
        ParameterValue::Integer(value) => ParameterValueWire::Integer(*value),
        ParameterValue::Scalar(value) => ParameterValueWire::ScalarBits(value.get().to_bits()),
        ParameterValue::Text(value) => ParameterValueWire::Text(value.to_string()),
        ParameterValue::Enum(value) => ParameterValueWire::Enum(value.to_string()),
    }
}

fn parameter_type_wire(value: ParameterType) -> ParameterTypeWire {
    match value {
        ParameterType::Boolean => ParameterTypeWire::Boolean,
        ParameterType::Integer => ParameterTypeWire::Integer,
        ParameterType::Scalar => ParameterTypeWire::Scalar,
        ParameterType::Text => ParameterTypeWire::Text,
        ParameterType::Enum => ParameterTypeWire::Enum,
    }
}

fn unit_wire(value: Unit) -> UnitWire {
    match value {
        Unit::Unitless => UnitWire::Unitless,
        Unit::Pixels => UnitWire::Pixels,
        Unit::Degrees => UnitWire::Degrees,
        Unit::Ratio => UnitWire::Ratio,
        Unit::Percent => UnitWire::Percent,
    }
}

fn unknown_records_wire(records: &[UnknownRecord]) -> Vec<UnknownRecordWire> {
    records
        .iter()
        .map(|record| UnknownRecordWire {
            kind: record.kind().to_owned(),
            payload: record.payload().to_vec(),
        })
        .collect()
}

fn node_authoring_wire(authoring: &NodeAuthoring) -> AuthoringWire {
    AuthoringWire {
        label: authoring.label.as_deref().map(str::to_owned),
        annotations: string_map(&authoring.annotations),
    }
}

fn string_map(values: &BTreeMap<Box<str>, Box<str>>) -> BTreeMap<String, String> {
    values.iter().map(|(key, value)| (key.to_string(), value.to_string())).collect()
}
