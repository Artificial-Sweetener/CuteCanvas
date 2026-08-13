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

//! Responsibility: Define caller-owned cancellation, execution budgets, and checked memory estimates.
//!
//! Does not own: thread pools, task scheduling, scratch allocation, caches, or product publication.

use std::fmt;
use std::num::NonZeroUsize;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Instant;

/// Cooperative cancellation token shared by one bounded evaluation request.
#[derive(Clone, Debug, Default)]
pub struct CancellationToken {
    cancelled: Arc<AtomicBool>,
}

impl CancellationToken {
    /// Construct an uncancelled token.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Request cancellation. Repeated calls are idempotent.
    pub fn cancel(&self) {
        self.cancelled.store(true, Ordering::Release);
    }

    /// Return whether cancellation has been requested.
    #[must_use]
    pub fn is_cancelled(&self) -> bool {
        self.cancelled.load(Ordering::Acquire)
    }

    /// Return a typed cancellation error when cancellation has been requested.
    ///
    /// # Errors
    ///
    /// Returns [`CancellationError`] after this token has been cancelled.
    pub fn check(&self) -> Result<(), CancellationError> {
        if self.is_cancelled() { Err(CancellationError) } else { Ok(()) }
    }
}

/// Expected termination caused by cooperative cancellation.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CancellationError;

impl fmt::Display for CancellationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("evaluation was cancelled")
    }
}

impl std::error::Error for CancellationError {}

/// Caller-supplied execution, scratch, and total-memory limits for one evaluation.
#[derive(Clone, Debug)]
pub struct ExecutionBudget {
    /// Maximum number of threads available to the request.
    pub threads: NonZeroUsize,
    /// Maximum scratch memory available across the request.
    pub scratch_bytes: u64,
    /// Maximum total native memory simultaneously owned by the request.
    pub memory_bytes: u64,
    /// Cooperative cancellation token.
    pub cancellation: CancellationToken,
    /// Optional monotonic completion deadline.
    pub deadline: Option<Instant>,
}

impl ExecutionBudget {
    /// Construct an execution budget without a deadline.
    #[must_use]
    pub const fn new(
        threads: NonZeroUsize,
        scratch_bytes: u64,
        memory_bytes: u64,
        cancellation: CancellationToken,
    ) -> Self {
        Self { threads, scratch_bytes, memory_bytes, cancellation, deadline: None }
    }

    /// Return whether cancellation or the deadline requires termination.
    #[must_use]
    pub fn should_cancel(&self, now: Instant) -> bool {
        self.cancellation.is_cancelled() || self.deadline.is_some_and(|deadline| now >= deadline)
    }

    /// Check cancellation against the current monotonic time.
    ///
    /// Token-only requests avoid reading the clock on hot polling paths.
    #[must_use]
    pub fn should_cancel_now(&self) -> bool {
        self.cancellation.is_cancelled()
            || self.deadline.is_some_and(|deadline| Instant::now() >= deadline)
    }
}

/// Checked memory estimate for one operation request.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct MemoryEstimate {
    /// Bytes reserved for unpublished destination products.
    pub destination_bytes: u64,
    /// Reusable temporary bytes required during execution.
    pub scratch_bytes: u64,
    /// Bytes retained by completed immutable products.
    pub retained_bytes: u64,
    /// Additional bytes simultaneously in flight.
    pub in_flight_bytes: u64,
}

impl MemoryEstimate {
    /// Return the maximum simultaneously admitted bytes.
    ///
    /// # Errors
    ///
    /// Returns [`MemoryEstimateError::Overflow`] when the byte classes cannot be summed.
    pub fn checked_peak_bytes(self) -> Result<u64, MemoryEstimateError> {
        [self.destination_bytes, self.scratch_bytes, self.retained_bytes, self.in_flight_bytes]
            .into_iter()
            .try_fold(0_u64, u64::checked_add)
            .ok_or(MemoryEstimateError::Overflow)
    }

    /// Return whether this request fits both total memory and scratch limits.
    ///
    /// # Errors
    ///
    /// Returns [`MemoryEstimateError::Overflow`] when peak memory cannot be represented.
    pub fn fits(self, total_limit: u64, scratch_limit: u64) -> Result<bool, MemoryEstimateError> {
        Ok(self.scratch_bytes <= scratch_limit && self.checked_peak_bytes()? <= total_limit)
    }
}

/// Error returned when memory accounting exceeds the representable byte domain.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MemoryEstimateError {
    /// The sum of independently accounted byte classes overflowed.
    Overflow,
    /// The requested product cannot be accounted by this operation.
    UnsupportedProduct,
    /// Invocation parameters are absent, ill-typed, or internally inconsistent.
    InvalidParameters,
}

impl fmt::Display for MemoryEstimateError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let message = match self {
            Self::Overflow => "memory estimate overflow",
            Self::UnsupportedProduct => "operation does not support the requested product",
            Self::InvalidParameters => "operation parameters are invalid",
        };
        formatter.write_str(message)
    }
}

impl std::error::Error for MemoryEstimateError {}

#[cfg(test)]
mod tests {
    use super::*;
    use std::num::NonZeroUsize;
    use std::time::Duration;

    #[test]
    fn cloned_cancellation_tokens_share_one_atomic_state() {
        let first = CancellationToken::new();
        let second = first.clone();

        assert_eq!(second.check(), Ok(()));
        first.cancel();
        assert_eq!(second.check(), Err(CancellationError));
    }

    #[test]
    fn current_time_check_honors_tokens_and_deadlines() {
        let token = CancellationToken::new();
        let mut budget = ExecutionBudget::new(NonZeroUsize::MIN, 1, 1, token.clone());
        assert!(!budget.should_cancel_now());

        token.cancel();
        assert!(budget.should_cancel_now());

        budget.cancellation = CancellationToken::new();
        budget.deadline =
            Some(Instant::now().checked_sub(Duration::from_millis(1)).unwrap_or_else(Instant::now));
        assert!(budget.should_cancel_now());
    }

    #[test]
    fn memory_admission_counts_each_owned_byte_class() {
        let estimate = MemoryEstimate {
            destination_bytes: 100,
            scratch_bytes: 20,
            retained_bytes: 50,
            in_flight_bytes: 30,
        };

        assert_eq!(estimate.checked_peak_bytes(), Ok(200));
        assert_eq!(estimate.fits(200, 20), Ok(true));
        assert_eq!(estimate.fits(199, 20), Ok(false));
        assert_eq!(estimate.fits(200, 19), Ok(false));
        assert_eq!(
            MemoryEstimate {
                destination_bytes: u64::MAX,
                scratch_bytes: 1,
                ..MemoryEstimate::default()
            }
            .checked_peak_bytes(),
            Err(MemoryEstimateError::Overflow)
        );
    }
}
