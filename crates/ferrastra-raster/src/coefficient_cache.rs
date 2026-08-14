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

//! Responsibility: Retain a bounded operation-local LRU of immutable resampling coefficients.
//!
//! Does not own: coefficient construction, execution scratch, graph products, or host caches.

use std::collections::{BTreeMap, VecDeque};
use std::sync::{Arc, Mutex, MutexGuard};

use ferrastra_core::{EdgeMode, ExecutionBudget, OperationExecutionError};

use crate::lanczos_coefficients::AxisTable;
use crate::sampling_contract::AxisSampling;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub(crate) struct AxisKey {
    pub(crate) output_start: i64,
    pub(crate) output_length: u64,
    pub(crate) source_length: u64,
    pub(crate) first_center_bits: u64,
    pub(crate) source_step_bits: u64,
    pub(crate) edge: EdgeMode,
}

impl AxisKey {
    pub(crate) fn new(output_start: i64, output_length: u64, sampling: AxisSampling) -> Self {
        Self {
            output_start,
            output_length,
            source_length: sampling.source_length,
            first_center_bits: sampling.first_center.to_bits(),
            source_step_bits: sampling.source_step.to_bits(),
            edge: sampling.edge,
        }
    }
}

#[derive(Debug)]
pub(crate) struct CoefficientCache {
    byte_limit: u64,
    state: Mutex<CacheState>,
}

impl CoefficientCache {
    pub(crate) fn new(byte_limit: u64) -> Self {
        Self { byte_limit, state: Mutex::new(CacheState::default()) }
    }

    pub(crate) fn get_or_build(
        &self,
        key: AxisKey,
        sampling: AxisSampling,
        budget: &ExecutionBudget,
    ) -> Result<Arc<AxisTable>, OperationExecutionError> {
        if let Some(table) = self.get(key) {
            return Ok(table);
        }
        let table =
            Arc::new(AxisTable::new(key.output_start, key.output_length, sampling, budget)?);
        let bytes = table.allocated_bytes()?;
        if bytes > self.byte_limit {
            return Ok(table);
        }
        let mut state = self.lock_state();
        if let Some(existing) = state.entries.get(&key).map(|entry| Arc::clone(&entry.table)) {
            state.touch(key);
            return Ok(existing);
        }
        state.evict_until_fits(bytes, self.byte_limit);
        state.retained_bytes = state
            .retained_bytes
            .checked_add(bytes)
            .ok_or(OperationExecutionError::InvalidProduct)?;
        state.order.push_back(key);
        state.entries.insert(key, CacheEntry { table: Arc::clone(&table), bytes });
        Ok(table)
    }

    fn get(&self, key: AxisKey) -> Option<Arc<AxisTable>> {
        let mut state = self.lock_state();
        let table = state.entries.get(&key).map(|entry| Arc::clone(&entry.table));
        if table.is_some() {
            state.touch(key);
        }
        table
    }

    fn lock_state(&self) -> MutexGuard<'_, CacheState> {
        match self.state.lock() {
            Ok(state) => state,
            Err(poisoned) => poisoned.into_inner(),
        }
    }
}

#[derive(Debug)]
struct CacheEntry {
    table: Arc<AxisTable>,
    bytes: u64,
}

#[derive(Debug, Default)]
struct CacheState {
    entries: BTreeMap<AxisKey, CacheEntry>,
    order: VecDeque<AxisKey>,
    retained_bytes: u64,
}

impl CacheState {
    fn touch(&mut self, key: AxisKey) {
        self.order.retain(|candidate| *candidate != key);
        self.order.push_back(key);
    }

    fn evict_until_fits(&mut self, incoming_bytes: u64, byte_limit: u64) {
        while self.retained_bytes.saturating_add(incoming_bytes) > byte_limit {
            let Some(key) = self.order.pop_front() else {
                break;
            };
            if let Some(entry) = self.entries.remove(&key) {
                self.retained_bytes = self.retained_bytes.saturating_sub(entry.bytes);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use std::num::NonZeroUsize;

    use ferrastra_core::CancellationToken;

    use super::*;

    #[test]
    fn repeated_axis_requests_reuse_one_immutable_table() {
        let cache = CoefficientCache::new(1_048_576);
        let sampling = AxisSampling::resize(16, 32, EdgeMode::Clamp)
            .unwrap_or_else(|error| unreachable!("valid sampling rejected: {error}"));
        let key = AxisKey::new(0, 32, sampling);

        let budget =
            ExecutionBudget::new(NonZeroUsize::MIN, 1_048_576, 1_048_576, CancellationToken::new());
        let first = cache
            .get_or_build(key, sampling, &budget)
            .unwrap_or_else(|error| unreachable!("valid table rejected: {error}"));
        let second = cache
            .get_or_build(key, sampling, &budget)
            .unwrap_or_else(|error| unreachable!("valid table rejected: {error}"));

        assert!(Arc::ptr_eq(&first, &second));
    }

    #[test]
    fn cancellation_rejects_coefficient_construction_without_retaining_partial_state() {
        let cache = CoefficientCache::new(1_048_576);
        let token = CancellationToken::new();
        token.cancel();
        let budget = ExecutionBudget::new(NonZeroUsize::MIN, 1_048_576, 1_048_576, token);
        let sampling = AxisSampling::resize(16, 32, EdgeMode::Clamp)
            .unwrap_or_else(|error| unreachable!("valid sampling rejected: {error}"));
        let key = AxisKey::new(0, 32, sampling);

        assert_eq!(
            cache.get_or_build(key, sampling, &budget),
            Err(OperationExecutionError::Cancelled)
        );
        assert!(cache.lock_state().entries.is_empty());
    }
}
