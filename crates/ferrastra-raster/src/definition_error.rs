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

//! Responsibility: Translate invalid static operation declarations into one construction error.
//!
//! Does not own: runtime execution errors, graph diagnostics, host admission, or recovery policy.

use std::fmt;

use ferrastra_core::{DescriptorError, IdentityError, ValueError};

/// Error returned when a built-in operation's static contract is invalid.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum OperationDefinitionError {
    /// Semantic identity declaration was invalid.
    Identity(IdentityError),
    /// Port or parameter identity declaration was invalid.
    Value(ValueError),
    /// Complete descriptor validation failed.
    Descriptor(DescriptorError),
}

impl fmt::Display for OperationDefinitionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Identity(error) => error.fmt(formatter),
            Self::Value(error) => error.fmt(formatter),
            Self::Descriptor(error) => error.fmt(formatter),
        }
    }
}

impl std::error::Error for OperationDefinitionError {}

impl From<IdentityError> for OperationDefinitionError {
    fn from(error: IdentityError) -> Self {
        Self::Identity(error)
    }
}

impl From<ValueError> for OperationDefinitionError {
    fn from(error: ValueError) -> Self {
        Self::Value(error)
    }
}

impl From<DescriptorError> for OperationDefinitionError {
    fn from(error: DescriptorError) -> Self {
        Self::Descriptor(error)
    }
}
