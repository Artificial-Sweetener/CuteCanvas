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

//! Responsibility: Assemble built-in operations with source retention, compilation, and evaluation.
//!
//! Does not own: subsystem behavior, graph construction policy, threading, caches, or bindings.

use std::collections::BTreeMap;
use std::sync::Arc;

use ferrastra_core::{
    CapabilitySet, ContentId, CoverageFormat, ExecutionBudget, IntRect, IntSize, ProductView,
    QualityTier, RasterFormat,
};
use ferrastra_graph::{CompiledPlan, GraphDefinition, GraphName, NodeId, compile_graph};
use ferrastra_raster::{
    AffineBilinearOperation, AffineNearestOperation, CoverageAffineOperation,
    CoverageSourceOperation, IdentityOperation, Lanczos3Operation, Lanczos3ViewOperation,
    RasterSourceOperation,
};
use ferrastra_runtime::{EvaluationRequirements, ImageSourceStores, evaluation_requirements};
use ferrastra_runtime::{EvaluationResult, OperationSet, evaluate, propagate_damage};
use ferrastra_store::{CoverageProduct, CoverageSourceStore, RasterProduct, RasterSourceStore};

use crate::EngineError;

/// Stable high-level assembly for the supported Ferrastra native workflow.
pub struct Engine {
    operations: OperationSet,
    raster_sources: RasterSourceStore,
    coverage_sources: CoverageSourceStore,
    capabilities: CapabilitySet,
}

impl Engine {
    /// Construct an engine with every built-in operation supported by this release.
    ///
    /// # Errors
    ///
    /// Returns [`EngineError`] if a built-in contract or registration is invalid.
    pub fn new() -> Result<Self, EngineError> {
        let mut operations = OperationSet::new();
        operations.register_operation(Arc::new(RasterSourceOperation::new()?))?;
        operations.register_operation(Arc::new(CoverageSourceOperation::new()?))?;
        operations.register_kernel(Arc::new(IdentityOperation::new()?))?;
        operations.register_kernel(Arc::new(Lanczos3Operation::new()?))?;
        operations.register_kernel(Arc::new(Lanczos3ViewOperation::new()?))?;
        operations.register_kernel(Arc::new(AffineBilinearOperation::new()?))?;
        operations.register_kernel(Arc::new(AffineNearestOperation::new()?))?;
        operations.register_kernel(Arc::new(CoverageAffineOperation::new()?))?;
        Ok(Self {
            operations,
            raster_sources: RasterSourceStore::new(),
            coverage_sources: CoverageSourceStore::new(),
            capabilities: CapabilitySet::default(),
        })
    }

    /// Copy and retain one borrowed raster as a canonical immutable source revision.
    ///
    /// # Errors
    ///
    /// Returns [`EngineError`] when raster adoption or retained-byte accounting fails.
    pub fn add_raster(&mut self, view: ProductView<'_>) -> Result<ContentId, EngineError> {
        let product = RasterProduct::copy_from(view)?;
        self.retain_raster(product)
    }

    /// Adopt one owned tightly packed raster as a canonical immutable source revision.
    ///
    /// This path transfers the caller's allocation without an additional pixel copy.
    ///
    /// # Errors
    ///
    /// Returns [`EngineError`] when the packed layout is invalid or retained-byte accounting
    /// cannot represent the product.
    pub fn add_raster_owned(
        &mut self,
        bytes: Vec<u8>,
        size: IntSize,
        format: RasterFormat,
    ) -> Result<ContentId, EngineError> {
        self.retain_raster(RasterProduct::from_tight_bytes(bytes, size, format)?)
    }

    fn retain_raster(&mut self, product: RasterProduct) -> Result<ContentId, EngineError> {
        let revision = self.raster_sources.insert(product)?;
        Ok(*revision.as_content_id())
    }

    /// Adopt one owned tightly packed coverage product as an immutable revision.
    ///
    /// # Errors
    ///
    /// Returns [`EngineError`] when the layout or retained-byte accounting is invalid.
    pub fn add_coverage_owned(
        &mut self,
        bytes: Vec<u8>,
        size: IntSize,
        format: CoverageFormat,
    ) -> Result<ContentId, EngineError> {
        let product = CoverageProduct::from_tight_bytes(bytes, size, format)?;
        let revision = self.coverage_sources.insert(product)?;
        Ok(*revision.as_content_id())
    }

    /// Validate and compile an immutable graph against the engine's operation catalog.
    ///
    /// # Errors
    ///
    /// Returns [`EngineError`] with structured graph diagnostics when compilation fails.
    pub fn compile(&self, graph: &GraphDefinition) -> Result<CompiledPlan, EngineError> {
        compile_graph(graph, &self.operations, &self.capabilities).map_err(Into::into)
    }

    /// Evaluate and atomically publish one named regional raster result.
    ///
    /// # Errors
    ///
    /// Returns [`EngineError`] without a partial result when bounded evaluation fails.
    pub fn evaluate(
        &self,
        compiled: &CompiledPlan,
        output_name: &GraphName,
        output_region: IntRect,
        quality: QualityTier,
        budget: &ExecutionBudget,
    ) -> Result<EvaluationResult, EngineError> {
        evaluate(
            compiled,
            output_name,
            output_region,
            quality,
            budget,
            &self.operations,
            &ImageSourceStores { rasters: &self.raster_sources, coverages: &self.coverage_sources },
        )
        .map_err(Into::into)
    }

    /// Return the minimum total and scratch budgets for one regional evaluation.
    ///
    /// # Errors
    ///
    /// Returns [`EngineError`] when demand, parameters, products, or memory cannot be planned.
    pub fn evaluation_requirements(
        &self,
        compiled: &CompiledPlan,
        output_name: &GraphName,
        output_region: IntRect,
        quality: QualityTier,
    ) -> Result<EvaluationRequirements, EngineError> {
        evaluation_requirements(compiled, output_name, output_region, quality, &self.operations)
            .map_err(Into::into)
    }

    /// Propagate exact source damage through a compiled plan.
    ///
    /// # Errors
    ///
    /// Returns [`EngineError`] when an operation contract or damage region is invalid.
    pub fn propagate_damage(
        &self,
        compiled: &CompiledPlan,
        source_node: NodeId,
        source_damage: IntRect,
    ) -> Result<BTreeMap<NodeId, IntRect>, EngineError> {
        propagate_damage(compiled, source_node, source_damage, &self.operations).map_err(Into::into)
    }
}
