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

//! Responsibility: Retain injected operation contracts and kernels for runtime dispatch.
//!
//! Does not own: first-party operation construction, graph validation, execution, or plugin loading.

use std::collections::BTreeMap;
use std::fmt;
use std::sync::Arc;

use ferrastra_core::{
    DescriptorError, Operation, OperationDescriptor, OperationIdentity, OperationKernel,
};
use ferrastra_graph::OperationCatalog;

/// Error returned before an invalid or duplicate operation enters a runtime registry.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RegistryError {
    /// The exact semantic operation version was already registered.
    DuplicateOperation,
    /// The operation's complete descriptor was invalid.
    InvalidDescriptor(DescriptorError),
}

impl fmt::Display for RegistryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::DuplicateOperation => formatter.write_str("operation is already registered"),
            Self::InvalidDescriptor(error) => error.fmt(formatter),
        }
    }
}

impl std::error::Error for RegistryError {}

/// Injected deterministic operation registry used by compilation and evaluation.
#[derive(Default)]
pub struct OperationSet {
    operations: BTreeMap<OperationIdentity, Arc<dyn Operation>>,
    kernels: BTreeMap<OperationIdentity, Arc<dyn OperationKernel>>,
}

impl OperationSet {
    /// Construct an empty operation set.
    #[must_use]
    pub const fn new() -> Self {
        Self { operations: BTreeMap::new(), kernels: BTreeMap::new() }
    }

    /// Register a non-kernel operation contract such as a runtime-resolved source.
    ///
    /// # Errors
    ///
    /// Returns [`RegistryError`] for an invalid descriptor or duplicate semantic identity.
    pub fn register_operation<T: Operation + 'static>(
        &mut self,
        operation: Arc<T>,
    ) -> Result<(), RegistryError> {
        operation.descriptor().validate().map_err(RegistryError::InvalidDescriptor)?;
        let identity = operation.descriptor().identity.clone();
        if self.operations.contains_key(&identity) {
            return Err(RegistryError::DuplicateOperation);
        }
        self.operations.insert(identity, operation);
        Ok(())
    }

    /// Register one executable pure operation as both its contract and numerical kernel.
    ///
    /// # Errors
    ///
    /// Returns [`RegistryError`] for an invalid descriptor or duplicate semantic identity.
    pub fn register_kernel<T: OperationKernel + 'static>(
        &mut self,
        operation: Arc<T>,
    ) -> Result<(), RegistryError> {
        operation.descriptor().validate().map_err(RegistryError::InvalidDescriptor)?;
        let identity = operation.descriptor().identity.clone();
        if self.operations.contains_key(&identity) {
            return Err(RegistryError::DuplicateOperation);
        }
        let operation_contract: Arc<dyn Operation> = operation.clone();
        let kernel: Arc<dyn OperationKernel> = operation;
        self.operations.insert(identity.clone(), operation_contract);
        self.kernels.insert(identity, kernel);
        Ok(())
    }

    /// Return one exact operation contract.
    #[must_use]
    pub fn operation(&self, identity: &OperationIdentity) -> Option<&dyn Operation> {
        self.operations.get(identity).map(AsRef::as_ref)
    }

    /// Return one exact executable kernel.
    #[must_use]
    pub fn kernel(&self, identity: &OperationIdentity) -> Option<&dyn OperationKernel> {
        self.kernels.get(identity).map(AsRef::as_ref)
    }
}

impl OperationCatalog for OperationSet {
    fn descriptor(&self, identity: &OperationIdentity) -> Option<&OperationDescriptor> {
        self.operation(identity).map(Operation::descriptor)
    }
}
