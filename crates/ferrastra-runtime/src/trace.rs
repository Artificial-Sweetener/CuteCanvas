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

//! Responsibility: Record deterministic per-node evaluation provenance without wall-clock policy.
//!
//! Does not own: logging, profiling storage, UI presentation, scheduling, or cache policy.

use ferrastra_core::{ContentId, IntRect};
use ferrastra_graph::{GraphContentId, NodeId};

/// Deterministic provenance for one evaluated reachable node.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NodeTrace {
    /// Stable authoring node identity.
    pub node: NodeId,
    /// Exact global output region produced.
    pub region: IntRect,
    /// Strong semantic product key assigned by the runtime.
    pub product_key: ContentId,
    /// Whether the node adopted an immutable source revision without a kernel invocation.
    pub source_adoption: bool,
}

/// Deterministic trace of one successfully published evaluation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EvaluationTrace {
    /// Normalized graph identity evaluated.
    pub graph: GraphContentId,
    /// Reachable node records in dependency-first execution order.
    pub nodes: Box<[NodeTrace]>,
}
