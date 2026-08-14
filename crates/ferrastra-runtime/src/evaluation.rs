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

//! Responsibility: Execute one admitted compiled raster-like request and publish one immutable result.
//!
//! Does not own: graph compilation, operation algorithms, source retention, host admission, or caches.

use ferrastra_core::{
    ContentId, EvaluationCounters, EvaluationOutcome, EvaluationReport, ExecutionBudget, IntRect,
    IntSize, OperationInput, OperationOutput, OperationRequest, ProductFormat, ProductSpec,
    ProductView, ProductViewMut, QualityTier,
};
use ferrastra_graph::{CompiledNode, CompiledPlan, GraphName, InputBinding, NodeId};
use ferrastra_store::ImageProduct;
use std::collections::BTreeMap;

use crate::demand::NodeDemand;
use crate::{EvaluationError, EvaluationTrace, ImageSourceProvider, NodeTrace, OperationSet};

/// Atomically published immutable raster result with deterministic report and trace.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EvaluationResult {
    /// Immutable exact raster or coverage product.
    pub product: ImageProduct,
    /// Stable outcome, product identity, memory, and work counters.
    pub report: EvaluationReport,
    /// Deterministic per-node provenance.
    pub trace: EvaluationTrace,
}

struct Produced {
    product: ImageProduct,
    product_key: ContentId,
    region: IntRect,
}

/// Evaluate one named regional raster output within caller-owned cancellation and memory limits.
///
/// # Errors
///
/// Returns [`EvaluationError`] without a published partial product when planning, source lookup,
/// memory admission, cancellation, layout validation, or operation execution fails.
pub fn evaluate(
    compiled: &CompiledPlan,
    output_name: &GraphName,
    output_region: IntRect,
    quality: QualityTier,
    budget: &ExecutionBudget,
    operations: &OperationSet,
    sources: &impl ImageSourceProvider,
) -> Result<EvaluationResult, EvaluationError> {
    if budget.should_cancel_now() {
        return Err(EvaluationError::Cancelled);
    }
    let demands = crate::demand::plan(compiled, output_name, output_region, quality, operations)?;
    let mut produced = BTreeMap::new();
    let mut traces = Vec::new();
    let mut retained_bytes = 0_u64;
    let mut peak_memory_bytes = 0_u64;
    let mut produced_samples = 0_u64;

    for node in compiled.nodes() {
        let Some(demand) = demands.get(&node.node) else {
            continue;
        };
        if budget.should_cancel_now() {
            return Err(EvaluationError::Cancelled);
        }
        let (product, input_keys, source_adoption) = if let Some(revision) =
            node.definition.source_revision.as_ref()
        {
            let source = source_product(sources, revision, demand.product)
                .ok_or(EvaluationError::MissingSource)?;
            admit_source_crop(
                &source,
                full_region(source.size())?,
                demand.region,
                retained_bytes,
                budget.memory_bytes,
            )?;
            (crop_product(&source, full_region(source.size())?, demand.region)?, Vec::new(), true)
        } else {
            let (product, input_keys, peak) = execute_kernel(
                node,
                demand,
                quality,
                budget,
                operations,
                &produced,
                retained_bytes,
            )?;
            peak_memory_bytes = peak_memory_bytes.max(peak);
            (product, input_keys, false)
        };
        retained_bytes = retained_bytes
            .checked_add(product.retained_bytes())
            .ok_or(ferrastra_core::MemoryEstimateError::Overflow)?;
        if retained_bytes > budget.memory_bytes {
            return Err(EvaluationError::MemoryLimitExceeded);
        }
        peak_memory_bytes = peak_memory_bytes.max(retained_bytes);
        produced_samples = produced_samples
            .checked_add(demand.region.size().checked_area()?)
            .ok_or(ferrastra_core::MemoryEstimateError::Overflow)?;
        let product_key = crate::product_key::derive(
            compiled.graph_content_id(),
            node.node,
            &input_keys,
            demand.region,
            demand.output_port.as_str(),
            demand.product,
            quality,
        );
        traces.push(NodeTrace {
            node: node.node,
            region: demand.region,
            product_key,
            source_adoption,
        });
        produced.insert(node.node, Produced { product, product_key, region: demand.region });
    }

    let output = compiled.outputs().get(output_name).ok_or(EvaluationError::UnknownOutput)?;
    let published = produced.remove(&output.node).ok_or(EvaluationError::MissingOperation)?;
    Ok(EvaluationResult {
        product: published.product,
        report: EvaluationReport {
            outcome: EvaluationOutcome::Completed(published.product_key),
            peak_memory_bytes,
            counters: EvaluationCounters {
                evaluated_nodes: u64::try_from(traces.len()).unwrap_or(u64::MAX),
                product_hits: 0,
                produced_samples,
            },
            diagnostics: Box::default(),
        },
        trace: EvaluationTrace {
            graph: compiled.graph_content_id(),
            nodes: traces.into_boxed_slice(),
        },
    })
}

fn source_product(
    sources: &impl ImageSourceProvider,
    revision: &ContentId,
    product: ProductSpec,
) -> Option<ImageProduct> {
    let format = product.format()?;
    let source = match format {
        ProductFormat::Raster(_) => sources
            .lease_raster(revision)
            .map(|lease| ImageProduct::Raster(lease.product().clone())),
        ProductFormat::Coverage(_) => sources
            .lease_coverage(revision)
            .map(|lease| ImageProduct::Coverage(lease.product().clone())),
    }?;
    (source.format() == format).then_some(source)
}

fn admit_source_crop(
    product: &ImageProduct,
    product_region: IntRect,
    requested: IntRect,
    retained_bytes: u64,
    memory_limit: u64,
) -> Result<(), EvaluationError> {
    if product_region.intersection(requested) != requested {
        return Err(EvaluationError::SourceRegionUnavailable);
    }
    let requested_bytes = u64::try_from(tight_length(
        requested.size(),
        usize::from(product.format().bytes_per_sample()),
    )?)
    .map_err(|_| EvaluationError::Product)?;
    let admitted = retained_bytes
        .checked_add(requested_bytes)
        .ok_or(ferrastra_core::MemoryEstimateError::Overflow)?;
    if admitted > memory_limit {
        return Err(EvaluationError::MemoryLimitExceeded);
    }
    Ok(())
}

fn execute_kernel(
    node: &CompiledNode,
    demand: &NodeDemand,
    quality: QualityTier,
    budget: &ExecutionBudget,
    operations: &OperationSet,
    produced: &BTreeMap<NodeId, Produced>,
    retained_bytes: u64,
) -> Result<(ImageProduct, Vec<ContentId>, u64), EvaluationError> {
    let operation = operations
        .operation(&node.definition.operation)
        .ok_or(EvaluationError::MissingOperation)?;
    let kernel =
        operations.kernel(&node.definition.operation).ok_or(EvaluationError::MissingOperation)?;
    let request = OperationRequest {
        output_region: demand.region,
        output: demand.product,
        quality,
        parameters: crate::parameters::resolve(&node.definition, operation.descriptor())?,
    };
    let memory = operation.memory(&request)?;
    if !memory.fits(budget.memory_bytes, budget.scratch_bytes)? {
        return Err(EvaluationError::MemoryLimitExceeded);
    }
    let peak = retained_bytes
        .checked_add(memory.checked_peak_bytes()?)
        .ok_or(ferrastra_core::MemoryEstimateError::Overflow)?;
    if peak > budget.memory_bytes {
        return Err(EvaluationError::MemoryLimitExceeded);
    }

    let required = operation.backward_demand(&request)?;
    let mut inputs = Vec::with_capacity(required.len());
    let mut input_keys = Vec::with_capacity(required.len());
    for input_demand in &required {
        let binding = node
            .definition
            .inputs
            .get(&input_demand.port)
            .ok_or(EvaluationError::ConflictingDemand)?;
        let InputBinding::Node(source) = binding else {
            return Err(EvaluationError::GraphInputUnsupported);
        };
        let source_product = produced.get(&source.node).ok_or(EvaluationError::MissingOperation)?;
        inputs.push(OperationInput {
            port: &input_demand.port,
            region: input_demand.region,
            product: regional_view(
                &source_product.product,
                source_product.region,
                input_demand.region,
            )?,
        });
        input_keys.push(source_product.product_key);
    }

    let format = demand.product.format().ok_or(EvaluationError::Product)?;
    let bytes_per_sample = usize::from(format.bytes_per_sample());
    let length = tight_length(demand.region.size(), bytes_per_sample)?;
    let stride = tight_stride(demand.region.size(), bytes_per_sample)?;
    let mut destination = vec![0_u8; length];
    let output_view = ProductViewMut::new(&mut destination, demand.region.size(), stride, format)?;
    kernel.execute(
        &request,
        &inputs,
        &mut [OperationOutput {
            port: &demand.output_port,
            region: demand.region,
            product: output_view,
        }],
        budget,
    )?;
    Ok((
        ImageProduct::from_tight_bytes(destination, demand.region.size(), format)?,
        input_keys,
        peak,
    ))
}

fn crop_product(
    product: &ImageProduct,
    product_region: IntRect,
    requested: IntRect,
) -> Result<ImageProduct, EvaluationError> {
    if requested == product_region {
        return Ok(product.clone());
    }
    let view = regional_view(product, product_region, requested)?;
    ImageProduct::copy_from(view).map_err(Into::into)
}

fn regional_view(
    product: &ImageProduct,
    product_region: IntRect,
    requested: IntRect,
) -> Result<ProductView<'_>, EvaluationError> {
    if requested.is_empty() {
        return ProductView::new(&[], requested.size(), 0, product.format()).map_err(Into::into);
    }
    if product_region.intersection(requested) != requested {
        return Err(EvaluationError::SourceRegionUnavailable);
    }
    let x = usize::try_from(requested.origin().x - product_region.origin().x)
        .map_err(|_| EvaluationError::SourceRegionUnavailable)?;
    let y = usize::try_from(requested.origin().y - product_region.origin().y)
        .map_err(|_| EvaluationError::SourceRegionUnavailable)?;
    let byte_offset = y
        .checked_mul(product.stride_bytes())
        .and_then(|offset| {
            x.checked_mul(usize::from(product.format().bytes_per_sample()))
                .and_then(|column| offset.checked_add(column))
        })
        .ok_or(EvaluationError::Product)?;
    let full = product.view()?;
    let bytes = full.bytes().get(byte_offset..).ok_or(EvaluationError::Product)?;
    ProductView::new(bytes, requested.size(), product.stride_bytes(), product.format())
        .map_err(Into::into)
}

fn full_region(size: IntSize) -> Result<IntRect, EvaluationError> {
    IntRect::new(0, 0, size.width, size.height).map_err(Into::into)
}

fn tight_stride(size: IntSize, bytes_per_sample: usize) -> Result<usize, EvaluationError> {
    usize::try_from(size.width)
        .ok()
        .and_then(|width| width.checked_mul(bytes_per_sample))
        .ok_or(EvaluationError::Product)
}

fn tight_length(size: IntSize, bytes_per_sample: usize) -> Result<usize, EvaluationError> {
    tight_stride(size, bytes_per_sample)?
        .checked_mul(usize::try_from(size.height).map_err(|_| EvaluationError::Product)?)
        .ok_or(EvaluationError::Product)
}
