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

//! Responsibility: Define validated semantic operation identities and opaque content identities.
//!
//! Does not own: content hashing, graph revision assignment, source revision storage, or caches.

use std::fmt;
use std::num::NonZeroU32;
use std::str::FromStr;

/// Error returned when an identity value is not canonical.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum IdentityError {
    /// A semantic identifier did not follow Ferrastra's stable identifier grammar.
    InvalidSemanticId,
    /// A semantic version was zero.
    ZeroSemanticVersion,
    /// A content identity did not contain exactly 64 hexadecimal digits.
    InvalidContentIdLength,
    /// A content identity contained a non-hexadecimal character.
    InvalidContentIdDigit,
}

impl fmt::Display for IdentityError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let message = match self {
            Self::InvalidSemanticId => "semantic operation ID is not canonical",
            Self::ZeroSemanticVersion => "semantic operation version must be positive",
            Self::InvalidContentIdLength => "content ID must contain 64 hexadecimal digits",
            Self::InvalidContentIdDigit => "content ID contains a non-hexadecimal digit",
        };
        formatter.write_str(message)
    }
}

impl std::error::Error for IdentityError {}

/// Stable lowercase dotted identifier for one operation's semantics.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct SemanticOperationId(Box<str>);

impl SemanticOperationId {
    /// Validate and construct a semantic operation identifier.
    ///
    /// Each dot-delimited segment starts with a lowercase ASCII letter and may continue with
    /// lowercase letters, digits, or hyphens.
    ///
    /// # Errors
    ///
    /// Returns [`IdentityError::InvalidSemanticId`] when the value is not canonical.
    pub fn new(value: impl Into<Box<str>>) -> Result<Self, IdentityError> {
        let value = value.into();
        if is_semantic_id(&value) { Ok(Self(value)) } else { Err(IdentityError::InvalidSemanticId) }
    }

    /// Return the canonical identifier text.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for SemanticOperationId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.as_str())
    }
}

impl FromStr for SemanticOperationId {
    type Err = IdentityError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Self::new(value)
    }
}

/// Positive version of an operation's numerical semantics.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct SemanticVersion(NonZeroU32);

impl SemanticVersion {
    /// Construct a positive semantic version.
    ///
    /// # Errors
    ///
    /// Returns [`IdentityError::ZeroSemanticVersion`] when `value` is zero.
    pub fn new(value: u32) -> Result<Self, IdentityError> {
        NonZeroU32::new(value).map(Self).ok_or(IdentityError::ZeroSemanticVersion)
    }

    /// Return the numeric semantic version.
    #[must_use]
    pub const fn get(self) -> u32 {
        self.0.get()
    }
}

impl fmt::Display for SemanticVersion {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.get().fmt(formatter)
    }
}

/// Complete stable identity of one versioned operation contract.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct OperationIdentity {
    semantic_id: SemanticOperationId,
    semantic_version: SemanticVersion,
}

impl OperationIdentity {
    /// Combine one semantic identifier with its positive semantic version.
    #[must_use]
    pub const fn new(semantic_id: SemanticOperationId, semantic_version: SemanticVersion) -> Self {
        Self { semantic_id, semantic_version }
    }

    /// Return the operation's semantic identifier.
    #[must_use]
    pub const fn semantic_id(&self) -> &SemanticOperationId {
        &self.semantic_id
    }

    /// Return the operation's semantic version.
    #[must_use]
    pub const fn semantic_version(&self) -> SemanticVersion {
        self.semantic_version
    }
}

impl fmt::Display for OperationIdentity {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}@{}", self.semantic_id, self.semantic_version)
    }
}

/// Opaque 256-bit identity for normalized content.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct ContentId([u8; Self::BYTE_LENGTH]);

impl ContentId {
    /// Number of bytes in a content identity.
    pub const BYTE_LENGTH: usize = 32;

    /// Construct an identity from an already computed digest.
    #[must_use]
    pub const fn from_bytes(bytes: [u8; Self::BYTE_LENGTH]) -> Self {
        Self(bytes)
    }

    /// Return the identity bytes.
    #[must_use]
    pub const fn as_bytes(&self) -> &[u8; Self::BYTE_LENGTH] {
        &self.0
    }
}

impl fmt::Display for ContentId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        for byte in self.0 {
            write!(formatter, "{byte:02x}")?;
        }
        Ok(())
    }
}

impl FromStr for ContentId {
    type Err = IdentityError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        if value.len() != Self::BYTE_LENGTH * 2 {
            return Err(IdentityError::InvalidContentIdLength);
        }
        let mut bytes = [0_u8; Self::BYTE_LENGTH];
        for (index, pair) in value.as_bytes().chunks_exact(2).enumerate() {
            let high = hexadecimal_value(pair[0]).ok_or(IdentityError::InvalidContentIdDigit)?;
            let low = hexadecimal_value(pair[1]).ok_or(IdentityError::InvalidContentIdDigit)?;
            bytes[index] = (high << 4) | low;
        }
        Ok(Self(bytes))
    }
}

fn is_semantic_id(value: &str) -> bool {
    value.split('.').all(|segment| {
        let mut characters = segment.bytes();
        characters.next().is_some_and(|first| first.is_ascii_lowercase())
            && characters.all(|character| {
                character.is_ascii_lowercase() || character.is_ascii_digit() || character == b'-'
            })
    }) && value.contains('.')
}

const fn hexadecimal_value(character: u8) -> Option<u8> {
    match character {
        b'0'..=b'9' => Some(character - b'0'),
        b'a'..=b'f' => Some(character - b'a' + 10),
        b'A'..=b'F' => Some(character - b'A' + 10),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn semantic_operation_ids_accept_only_canonical_segments() {
        let identity = SemanticOperationId::new("ferrastra.resample.lanczos3")
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"));

        assert_eq!(identity.as_str(), "ferrastra.resample.lanczos3");
        for invalid in ["lanczos3", "Ferrastra.resize", "ferrastra..resize", "9.resize"] {
            assert_eq!(SemanticOperationId::new(invalid), Err(IdentityError::InvalidSemanticId));
        }
    }

    #[test]
    fn operation_identity_separates_semantics_from_crate_versions() {
        let semantic_id = SemanticOperationId::new("ferrastra.source.raster")
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"));
        let semantic_version = SemanticVersion::new(1)
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"));

        assert_eq!(
            OperationIdentity::new(semantic_id, semantic_version).to_string(),
            "ferrastra.source.raster@1"
        );
        assert_eq!(SemanticVersion::new(0), Err(IdentityError::ZeroSemanticVersion));
    }

    #[test]
    fn content_identity_round_trips_canonical_hexadecimal() {
        let bytes = std::array::from_fn(|index| u8::try_from(index).unwrap_or_default());
        let identity = ContentId::from_bytes(bytes);
        let rendered = identity.to_string();

        assert_eq!(rendered.len(), 64);
        assert_eq!(rendered.parse::<ContentId>(), Ok(identity));
        assert_eq!("00".parse::<ContentId>(), Err(IdentityError::InvalidContentIdLength));
        assert_eq!(
            format!("{}zz", &rendered[..62]).parse::<ContentId>(),
            Err(IdentityError::InvalidContentIdDigit)
        );
    }
}
