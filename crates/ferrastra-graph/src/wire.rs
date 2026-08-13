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

//! Responsibility: Define the private versioned wire records used by canonical graph JSON.
//!
//! Does not own: graph semantics, validation, normalization, public types, or I/O.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

#[derive(Deserialize, Serialize)]
pub(crate) struct GraphWire {
    pub(crate) schema_version: u32,
    pub(crate) revision_id: u64,
    pub(crate) content_id: String,
    pub(crate) inputs: Vec<NamedProductWire>,
    pub(crate) exposed_parameters: Vec<NamedExposedParameterWire>,
    pub(crate) nodes: Vec<NodeWire>,
    pub(crate) outputs: Vec<NamedOutputWire>,
    pub(crate) unknown_records: Vec<UnknownRecordWire>,
    pub(crate) authoring: AuthoringWire,
}

#[derive(Deserialize, Serialize)]
pub(crate) struct NamedProductWire {
    pub(crate) name: String,
    pub(crate) product: ProductWire,
}

#[derive(Clone, Copy, Deserialize, Serialize)]
pub(crate) struct ProductWire {
    pub(crate) kind: ProductKindWire,
    pub(crate) format: Option<ProductFormatWire>,
}

#[derive(Clone, Copy, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum ProductKindWire {
    Raster,
    Coverage,
    Vector,
    Graphic,
    Scalar,
    Color,
    Transform,
    Metadata,
}

#[derive(Clone, Copy, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum ProductFormatWire {
    Rgba8PremultipliedEncoded,
    Rgba16PremultipliedLinear,
    Rgba32FloatPremultipliedLinear,
    Coverage8,
    Coverage16,
    Coverage32Float,
}

#[derive(Deserialize, Serialize)]
pub(crate) struct NamedExposedParameterWire {
    pub(crate) name: String,
    pub(crate) parameter: ExposedParameterWire,
}

#[derive(Deserialize, Serialize)]
pub(crate) struct ExposedParameterWire {
    pub(crate) node: u64,
    pub(crate) parameter: String,
    pub(crate) parameter_type: ParameterTypeWire,
    pub(crate) unit: UnitWire,
    pub(crate) default: ParameterValueWire,
}

#[derive(Clone, Copy, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum ParameterTypeWire {
    Boolean,
    Integer,
    Scalar,
    Text,
    Enum,
}

#[derive(Clone, Copy, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum UnitWire {
    Unitless,
    Pixels,
    Degrees,
    Ratio,
    Percent,
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "type", content = "value", rename_all = "snake_case")]
pub(crate) enum ParameterValueWire {
    Boolean(bool),
    Integer(i64),
    ScalarBits(u64),
    Text(String),
    Enum(String),
}

#[derive(Deserialize, Serialize)]
pub(crate) struct NodeWire {
    pub(crate) id: u64,
    pub(crate) operation_id: String,
    pub(crate) operation_version: u32,
    pub(crate) parameters: Vec<NamedParameterBindingWire>,
    pub(crate) inputs: Vec<NamedInputBindingWire>,
    pub(crate) source_revision: Option<String>,
    pub(crate) unknown_records: Vec<UnknownRecordWire>,
    pub(crate) authoring: AuthoringWire,
}

#[derive(Deserialize, Serialize)]
pub(crate) struct NamedParameterBindingWire {
    pub(crate) parameter: String,
    pub(crate) binding: ParameterBindingWire,
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "type", content = "value", rename_all = "snake_case")]
pub(crate) enum ParameterBindingWire {
    Constant(ParameterValueWire),
    Exposed(String),
}

#[derive(Deserialize, Serialize)]
pub(crate) struct NamedInputBindingWire {
    pub(crate) port: String,
    pub(crate) binding: InputBindingWire,
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "type", content = "value", rename_all = "snake_case")]
pub(crate) enum InputBindingWire {
    GraphInput(String),
    Node(NodeOutputWire),
}

#[derive(Deserialize, Serialize)]
pub(crate) struct NamedOutputWire {
    pub(crate) name: String,
    pub(crate) output: NodeOutputWire,
}

#[derive(Deserialize, Serialize)]
pub(crate) struct NodeOutputWire {
    pub(crate) node: u64,
    pub(crate) port: String,
}

#[derive(Deserialize, Serialize)]
pub(crate) struct UnknownRecordWire {
    pub(crate) kind: String,
    pub(crate) payload: Vec<u8>,
}

#[derive(Deserialize, Serialize)]
pub(crate) struct AuthoringWire {
    pub(crate) label: Option<String>,
    pub(crate) annotations: BTreeMap<String, String>,
}
