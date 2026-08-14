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

//! Responsibility: Encode normalized computational graph state and derive strong content identity.
//!
//! Does not own: full-fidelity graph serialization, authoring metadata, validation, or compilation.

use std::collections::BTreeMap;

use ferrastra_core::{
    ContentId, CoverageFormat, ParameterType, ParameterValue, ProductFormat, ProductKind,
    ProductSpec, RasterFormat, Unit,
};

use crate::definition::{
    ExposedParameter, GraphName, InputBinding, NodeDefinition, NodeOutput, ParameterBinding,
    UnknownRecord,
};
use crate::{GraphContentId, GraphSchemaVersion, NodeId};

pub(crate) fn content_id(
    schema_version: GraphSchemaVersion,
    inputs: &BTreeMap<GraphName, ProductSpec>,
    exposed_parameters: &BTreeMap<GraphName, ExposedParameter>,
    nodes: &BTreeMap<NodeId, NodeDefinition>,
    outputs: &BTreeMap<GraphName, NodeOutput>,
    unknown_records: &[UnknownRecord],
) -> GraphContentId {
    let mut encoder = Encoder::default();
    encoder.bytes(b"FERRASTRA_GRAPH_CONTENT\0");
    encoder.u32(schema_version.get());
    encoder.map(inputs, |encoder, name, product| {
        encoder.string(name.as_str());
        encoder.product(*product);
    });
    encoder.map(exposed_parameters, |encoder, name, parameter| {
        encoder.string(name.as_str());
        encoder.u64(parameter.node.get());
        encoder.string(parameter.parameter.as_str());
        encoder.parameter_type(parameter.parameter_type);
        encoder.unit(parameter.unit);
        encoder.parameter_value(&parameter.default);
    });
    encoder.map(nodes, |encoder, node_id, node| {
        encoder.u64(node_id.get());
        encoder.string(node.operation.semantic_id().as_str());
        encoder.u32(node.operation.semantic_version().get());
        encoder.optional(node.source_revision.as_ref(), |encoder, revision| {
            encoder.bytes(revision.as_bytes());
        });
        encoder.map(&node.parameters, |encoder, parameter, binding| {
            encoder.string(parameter.as_str());
            match binding {
                ParameterBinding::Constant(value) => {
                    encoder.u8(0);
                    encoder.parameter_value(value);
                }
                ParameterBinding::Exposed(name) => {
                    encoder.u8(1);
                    encoder.string(name.as_str());
                }
            }
        });
        encoder.map(&node.inputs, |encoder, port, binding| {
            encoder.string(port.as_str());
            match binding {
                InputBinding::GraphInput(name) => {
                    encoder.u8(0);
                    encoder.string(name.as_str());
                }
                InputBinding::Node(output) => {
                    encoder.u8(1);
                    encoder.node_output(output);
                }
            }
        });
        encoder.unknown_records(&node.unknown_records);
    });
    encoder.map(outputs, |encoder, name, output| {
        encoder.string(name.as_str());
        encoder.node_output(output);
    });
    encoder.unknown_records(unknown_records);
    GraphContentId::from_content_id(ContentId::from_bytes(*blake3::hash(&encoder.data).as_bytes()))
}

#[derive(Default)]
struct Encoder {
    data: Vec<u8>,
}

impl Encoder {
    fn u8(&mut self, value: u8) {
        self.data.push(value);
    }

    fn u32(&mut self, value: u32) {
        self.data.extend_from_slice(&value.to_le_bytes());
    }

    fn u64(&mut self, value: u64) {
        self.data.extend_from_slice(&value.to_le_bytes());
    }

    fn bytes(&mut self, value: &[u8]) {
        self.u64(u64::try_from(value.len()).unwrap_or(u64::MAX));
        self.data.extend_from_slice(value);
    }

    fn string(&mut self, value: &str) {
        self.bytes(value.as_bytes());
    }

    fn optional<T>(&mut self, value: Option<&T>, encode: impl FnOnce(&mut Self, &T)) {
        if let Some(value) = value {
            self.u8(1);
            encode(self, value);
        } else {
            self.u8(0);
        }
    }

    fn map<K, V>(&mut self, values: &BTreeMap<K, V>, mut encode: impl FnMut(&mut Self, &K, &V)) {
        self.u64(u64::try_from(values.len()).unwrap_or(u64::MAX));
        for (key, value) in values {
            encode(self, key, value);
        }
    }

    fn node_output(&mut self, output: &NodeOutput) {
        self.u64(output.node.get());
        self.string(output.port.as_str());
    }

    fn unknown_records(&mut self, records: &[UnknownRecord]) {
        self.u64(u64::try_from(records.len()).unwrap_or(u64::MAX));
        for record in records {
            self.string(record.kind());
            self.bytes(record.payload());
        }
    }

    fn parameter_type(&mut self, parameter_type: ParameterType) {
        self.u8(match parameter_type {
            ParameterType::Boolean => 0,
            ParameterType::Integer => 1,
            ParameterType::Scalar => 2,
            ParameterType::Text => 3,
            ParameterType::Enum => 4,
        });
    }

    fn unit(&mut self, unit: Unit) {
        self.u8(match unit {
            Unit::Unitless => 0,
            Unit::Pixels => 1,
            Unit::Degrees => 2,
            Unit::Ratio => 3,
            Unit::Percent => 4,
        });
    }

    fn parameter_value(&mut self, value: &ParameterValue) {
        match value {
            ParameterValue::Boolean(value) => {
                self.u8(0);
                self.u8(u8::from(*value));
            }
            ParameterValue::Integer(value) => {
                self.u8(1);
                self.data.extend_from_slice(&value.to_le_bytes());
            }
            ParameterValue::Scalar(value) => {
                self.u8(2);
                self.data.extend_from_slice(&value.get().to_bits().to_le_bytes());
            }
            ParameterValue::Text(value) => {
                self.u8(3);
                self.string(value);
            }
            ParameterValue::Enum(value) => {
                self.u8(4);
                self.string(value.as_str());
            }
        }
    }

    fn product(&mut self, product: ProductSpec) {
        self.u8(match product.kind() {
            ProductKind::Raster => 0,
            ProductKind::Coverage => 1,
            ProductKind::Vector => 2,
            ProductKind::Graphic => 3,
            ProductKind::Scalar => 4,
            ProductKind::Color => 5,
            ProductKind::Transform => 6,
            ProductKind::Metadata => 7,
        });
        self.optional(product.format().as_ref(), |encoder, format| {
            encoder.u8(match format {
                ProductFormat::Raster(RasterFormat::Rgba8PremultipliedEncoded) => 0x10,
                ProductFormat::Raster(RasterFormat::Rgba16PremultipliedLinear) => 0x11,
                ProductFormat::Raster(RasterFormat::Rgba32FloatPremultipliedLinear) => 0x12,
                ProductFormat::Coverage(CoverageFormat::Coverage8) => 0x20,
                ProductFormat::Coverage(CoverageFormat::Coverage16) => 0x21,
                ProductFormat::Coverage(CoverageFormat::Coverage32Float) => 0x22,
            });
        });
    }
}
