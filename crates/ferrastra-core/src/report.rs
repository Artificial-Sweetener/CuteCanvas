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

//! Responsibility: Define stable evaluation outcomes, counters, and report records.
//!
//! Does not own: evaluation execution, tracing storage, host logging, or diagnostic presentation.

use crate::{ContentId, Diagnostic};

/// Terminal outcome of one bounded evaluation request.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EvaluationOutcome {
    /// An immutable product was published atomically.
    Completed(ContentId),
    /// Cooperative cancellation ended evaluation without publication.
    Cancelled,
    /// Validation or host admission rejected the request before execution.
    Rejected,
    /// Execution failed without publishing a partial product.
    Failed,
}

/// Deterministic work counts recorded independently of wall-clock timing.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct EvaluationCounters {
    /// Graph nodes whose operation implementation executed.
    pub evaluated_nodes: u64,
    /// Requested node products satisfied by retained immutable products.
    pub product_hits: u64,
    /// Output sample positions produced during execution.
    pub produced_samples: u64,
}

/// Stable report returned for every accepted evaluation attempt.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EvaluationReport {
    /// Terminal outcome and published identity, when successful.
    pub outcome: EvaluationOutcome,
    /// Maximum simultaneously owned bytes observed by the runtime.
    pub peak_memory_bytes: u64,
    /// Deterministic execution counters.
    pub counters: EvaluationCounters,
    /// Structured diagnostics accumulated at recoverable boundaries.
    pub diagnostics: Box<[Diagnostic]>,
}

impl EvaluationReport {
    /// Return the immutable product identity only after successful publication.
    #[must_use]
    pub const fn product_id(&self) -> Option<ContentId> {
        match self.outcome {
            EvaluationOutcome::Completed(product_id) => Some(product_id),
            EvaluationOutcome::Cancelled
            | EvaluationOutcome::Rejected
            | EvaluationOutcome::Failed => None,
        }
    }

    /// Return whether evaluation ended without publishing a product.
    #[must_use]
    pub const fn is_terminal_without_product(&self) -> bool {
        self.product_id().is_none()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reports_couple_published_identity_only_to_completion() {
        let product_id = ContentId::from_bytes([7; ContentId::BYTE_LENGTH]);
        let completed = EvaluationReport {
            outcome: EvaluationOutcome::Completed(product_id),
            peak_memory_bytes: 128,
            counters: EvaluationCounters {
                evaluated_nodes: 2,
                product_hits: 1,
                produced_samples: 64,
            },
            diagnostics: Box::default(),
        };
        let cancelled = EvaluationReport {
            outcome: EvaluationOutcome::Cancelled,
            peak_memory_bytes: 64,
            counters: EvaluationCounters::default(),
            diagnostics: Box::default(),
        };

        assert_eq!(completed.product_id(), Some(product_id));
        assert!(!completed.is_terminal_without_product());
        assert!(cancelled.is_terminal_without_product());
    }
}
