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

//! Responsibility: Define stable structured diagnostic codes, targets, severity, and related records.
//!
//! Does not own: frontend source spans, localized rendering, graph validation, or repair application.

use std::fmt;
use std::str::FromStr;

use crate::{ParameterId, PortId, SemanticOperationId};

/// Error returned when a diagnostic record is not stable or actionable.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DiagnosticError {
    /// The diagnostic code was not uppercase ASCII with underscore separators.
    InvalidCode,
    /// The human-readable message was empty.
    EmptyMessage,
}

impl fmt::Display for DiagnosticError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let message = match self {
            Self::InvalidCode => "diagnostic code is not canonical",
            Self::EmptyMessage => "diagnostic message must not be empty",
        };
        formatter.write_str(message)
    }
}

impl std::error::Error for DiagnosticError {}

/// Stable machine-readable diagnostic code.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct DiagnosticCode(Box<str>);

impl DiagnosticCode {
    /// Validate and construct an uppercase underscore-delimited code.
    ///
    /// # Errors
    ///
    /// Returns [`DiagnosticError::InvalidCode`] when the value is not canonical.
    pub fn new(value: impl Into<Box<str>>) -> Result<Self, DiagnosticError> {
        let value = value.into();
        let mut characters = value.bytes();
        let valid = characters.next().is_some_and(|first| first.is_ascii_uppercase())
            && characters.all(|character| {
                character.is_ascii_uppercase() || character.is_ascii_digit() || character == b'_'
            });
        if valid { Ok(Self(value)) } else { Err(DiagnosticError::InvalidCode) }
    }

    /// Return the canonical diagnostic code.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for DiagnosticCode {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.as_str())
    }
}

impl FromStr for DiagnosticCode {
    type Err = DiagnosticError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Self::new(value)
    }
}

/// Severity of one structured diagnostic.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum DiagnosticSeverity {
    /// Informational analysis result.
    Information,
    /// Non-fatal condition that deserves attention.
    Warning,
    /// Condition that prevents the requested action.
    Error,
}

/// Stable computation target of a diagnostic.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct DiagnosticTarget {
    /// Optional operation semantic identity.
    pub operation: Option<SemanticOperationId>,
    /// Optional graph-owned node identifier represented canonically by the graph layer.
    pub node: Option<Box<str>>,
    /// Optional port identifier.
    pub port: Option<PortId>,
    /// Optional parameter identifier.
    pub parameter: Option<ParameterId>,
}

/// One stable structured diagnostic with optional related records.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Diagnostic {
    /// Stable machine-readable code.
    pub code: DiagnosticCode,
    /// Severity.
    pub severity: DiagnosticSeverity,
    /// Computation target.
    pub target: DiagnosticTarget,
    /// Concise human-readable message.
    pub message: Box<str>,
    /// Additional structured context as stable key/value pairs.
    pub details: Box<[(Box<str>, Box<str>)]>,
    /// Related diagnostics that provide causal context.
    pub related: Box<[Diagnostic]>,
}

impl Diagnostic {
    /// Construct a diagnostic after rejecting empty human-readable text.
    ///
    /// # Errors
    ///
    /// Returns [`DiagnosticError::EmptyMessage`] when `message` contains no visible text.
    pub fn new(
        code: DiagnosticCode,
        severity: DiagnosticSeverity,
        target: DiagnosticTarget,
        message: impl Into<Box<str>>,
    ) -> Result<Self, DiagnosticError> {
        let message = message.into();
        if message.trim().is_empty() {
            return Err(DiagnosticError::EmptyMessage);
        }
        Ok(Self {
            code,
            severity,
            target,
            message,
            details: Box::default(),
            related: Box::default(),
        })
    }

    /// Return whether this diagnostic prevents the requested action.
    #[must_use]
    pub const fn is_error(&self) -> bool {
        matches!(self.severity, DiagnosticSeverity::Error)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn diagnostic_codes_and_messages_are_stable_at_construction() {
        let code = DiagnosticCode::new("UNKNOWN_OPERATION")
            .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"));
        let diagnostic = Diagnostic::new(
            code,
            DiagnosticSeverity::Error,
            DiagnosticTarget::default(),
            "Operation is unavailable.",
        )
        .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}"));

        assert!(diagnostic.is_error());
        assert_eq!(DiagnosticCode::new("unknown-operation"), Err(DiagnosticError::InvalidCode));
        assert_eq!(
            Diagnostic::new(
                DiagnosticCode::new("EMPTY")
                    .unwrap_or_else(|error| unreachable!("valid fixture rejected: {error}")),
                DiagnosticSeverity::Warning,
                DiagnosticTarget::default(),
                "  ",
            ),
            Err(DiagnosticError::EmptyMessage)
        );
    }
}
