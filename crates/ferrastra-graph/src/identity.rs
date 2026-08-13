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

//! Responsibility: Define stable node, graph revision, and normalized graph content identities.
//!
//! Does not own: identity allocation, graph storage, normalization, patching, or product keys.

use std::fmt;
use std::num::NonZeroU32;
use std::num::NonZeroU64;

use ferrastra_core::ContentId;

/// Error returned when a graph-local identity violates its stable domain.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum GraphIdentityError {
    /// Node identifiers start at one.
    ZeroNodeId,
    /// Graph revision identifiers start at one.
    ZeroRevisionId,
    /// Graph schema versions start at one.
    ZeroSchemaVersion,
}

impl fmt::Display for GraphIdentityError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let message = match self {
            Self::ZeroNodeId => "node identifier must be positive",
            Self::ZeroRevisionId => "graph revision identifier must be positive",
            Self::ZeroSchemaVersion => "graph schema version must be positive",
        };
        formatter.write_str(message)
    }
}

impl std::error::Error for GraphIdentityError {}

/// Positive version of the canonical graph serialization schema.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct GraphSchemaVersion(NonZeroU32);

impl GraphSchemaVersion {
    /// Construct a positive graph schema version.
    ///
    /// # Errors
    ///
    /// Returns [`GraphIdentityError::ZeroSchemaVersion`] when `value` is zero.
    pub fn new(value: u32) -> Result<Self, GraphIdentityError> {
        NonZeroU32::new(value).map(Self).ok_or(GraphIdentityError::ZeroSchemaVersion)
    }

    /// Return the schema version number.
    #[must_use]
    pub const fn get(self) -> u32 {
        self.0.get()
    }
}

/// Stable authoring identity of one graph node.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct NodeId(NonZeroU64);

impl NodeId {
    /// Construct a positive node identifier.
    ///
    /// # Errors
    ///
    /// Returns [`GraphIdentityError::ZeroNodeId`] when `value` is zero.
    pub fn new(value: u64) -> Result<Self, GraphIdentityError> {
        NonZeroU64::new(value).map(Self).ok_or(GraphIdentityError::ZeroNodeId)
    }

    /// Return the stable numerical value.
    #[must_use]
    pub const fn get(self) -> u64 {
        self.0.get()
    }
}

impl fmt::Display for NodeId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.get().fmt(formatter)
    }
}

/// Monotonic identity of one immutable revision in a graph lineage.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct GraphRevisionId(NonZeroU64);

impl GraphRevisionId {
    /// Construct a positive revision identifier.
    ///
    /// # Errors
    ///
    /// Returns [`GraphIdentityError::ZeroRevisionId`] when `value` is zero.
    pub fn new(value: u64) -> Result<Self, GraphIdentityError> {
        NonZeroU64::new(value).map(Self).ok_or(GraphIdentityError::ZeroRevisionId)
    }

    /// Return the stable numerical value.
    #[must_use]
    pub const fn get(self) -> u64 {
        self.0.get()
    }
}

impl fmt::Display for GraphRevisionId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.get().fmt(formatter)
    }
}

/// Strong identity of one normalized computational graph definition.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct GraphContentId(ContentId);

impl GraphContentId {
    /// Construct an identity from a normalized graph digest.
    #[must_use]
    pub const fn from_content_id(content_id: ContentId) -> Self {
        Self(content_id)
    }

    /// Return the underlying normalized content identity.
    #[must_use]
    pub const fn as_content_id(&self) -> &ContentId {
        &self.0
    }
}

impl fmt::Display for GraphContentId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn graph_local_identifiers_reject_zero() {
        assert_eq!(NodeId::new(0), Err(GraphIdentityError::ZeroNodeId));
        assert_eq!(GraphRevisionId::new(0), Err(GraphIdentityError::ZeroRevisionId));
        assert_eq!(
            NodeId::new(7)
                .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"))
                .to_string(),
            "7"
        );
    }
}
