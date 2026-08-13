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

//! Responsibility: Provide the canonical versioned graph JSON boundary and actionable codec errors.
//!
//! Does not own: graph semantics, normalization identity, validation, file I/O, or frontend policy.

use std::fmt;

use crate::GraphDefinition;

/// Error returned when canonical graph JSON cannot be encoded or reconstructed.
#[derive(Debug)]
pub enum GraphCodecError {
    /// JSON syntax or data representation was invalid.
    Json(serde_json::Error),
    /// A typed graph record violated its canonical domain.
    InvalidRecord(Box<str>),
    /// The serialized computational identity did not match reconstructed content.
    ContentIdentityMismatch,
}

impl GraphCodecError {
    pub(crate) fn invalid(error: impl fmt::Display) -> Self {
        Self::InvalidRecord(error.to_string().into())
    }
}

impl fmt::Display for GraphCodecError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Json(error) => write!(formatter, "invalid canonical graph JSON: {error}"),
            Self::InvalidRecord(error) => write!(formatter, "invalid graph record: {error}"),
            Self::ContentIdentityMismatch => {
                formatter.write_str("serialized graph content identity does not match its records")
            }
        }
    }
}

impl std::error::Error for GraphCodecError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Json(error) => Some(error),
            Self::InvalidRecord(_) | Self::ContentIdentityMismatch => None,
        }
    }
}

/// Encode one graph as deterministic compact UTF-8 JSON.
///
/// # Errors
///
/// Returns [`GraphCodecError::Json`] if the private canonical record cannot be encoded.
pub fn serialize_graph(graph: &GraphDefinition) -> Result<Box<[u8]>, GraphCodecError> {
    serde_json::to_vec(&crate::encode::wire_graph(graph))
        .map(Vec::into_boxed_slice)
        .map_err(GraphCodecError::Json)
}

/// Decode canonical UTF-8 JSON and verify its normalized computational identity.
///
/// # Errors
///
/// Returns [`GraphCodecError`] for malformed JSON, invalid typed records, duplicates, or an
/// identity mismatch.
pub fn deserialize_graph(bytes: &[u8]) -> Result<GraphDefinition, GraphCodecError> {
    let wire = serde_json::from_slice(bytes).map_err(GraphCodecError::Json)?;
    crate::decode::graph(wire)
}
