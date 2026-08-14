# Ferrastra API reference

Import supported Python APIs from `ferrastra`. The `_native` module is a private
wheel implementation detail.

`RasterReconstructionSpace` names the supported working-space contracts for
sRGB premultiplied RGBA8 reconstruction: `SRGB_ENCODED` and `SRGB_LINEAR`.
This selects reconstruction math; it is not a general color-management or
profile-conversion API.

## Graph construction

`GraphBuilder(revision_id, *, schema_version=1)` constructs immutable graph
snapshots. Node identities are positive integers. Operation identities use a
canonical dotted semantic ID and a positive semantic version.

- `add_node(node_id, operation_id, *, semantic_version=1)` adds one typed node.
- `set_source_revision(node_id, revision)` binds a 64-digit content identity.
- `connect(source_node, source_port, destination_node, destination_port)` binds
  one named output to one named input.
- `add_output(name, node_id, *, port_name="result")` publishes a named output.
- `set_boolean`, `set_integer`, `set_scalar`, `set_text`, and `set_enum` bind
  canonical typed constant parameters.
- `set_label(label)` sets authoring metadata excluded from computational
  identity.
- `build()` returns an immutable `Graph` snapshot and leaves the builder usable.

`Graph.content_id` is the normalized computational identity. `Graph.to_json()`
returns canonical deterministic JSON. `Graph.from_json(serialized)` verifies the
embedded content identity before adopting a graph. Unknown operation records
remain serializable but fail compilation until their exact semantic version is
available.

## Sources and evaluation

`Engine()` assembles the built-in operation catalog, source store, compiler, and
bounded runtime.

`Engine.add_rgba8(data, width, height, *, stride_bytes=None)` copies a
one-dimensional, C-contiguous, unsigned-byte buffer into one canonical tightly
packed premultiplied encoded RGBA8 source revision. Row padding is excluded from
source identity. Invalid dimensions, strides, formats, and spans raise
`BufferError` before publication.

`Engine.add_coverage8(data, width, height, *, stride_bytes=None)` copies a
one-channel unsigned-byte coverage buffer into a canonical Coverage8 revision.
Coverage is scalar geometry data: it has no color channels, transfer function,
or premultiplied-alpha interpretation.

`Engine.compile(graph)` validates a graph and returns an immutable
`CompiledGraph`. `Engine.requirements(compiled, output_name, region)` returns
immutable `EvaluationRequirements` with the minimum `memory_bytes` and
`scratch_bytes` needed to admit that exact regional request.
`Engine.evaluate(compiled, output_name, region, budget)` returns an immutable
`RasterResult` or `CoverageResult` after exact regional evaluation completes.
Native evaluation releases the Python interpreter lock.

`Region(x, y, width, height)` represents a checked half-open integer region.
`EvaluationBudget` requires an explicit `memory_bytes` limit and accepts
`scratch_bytes`, `threads`, and a shared `CancellationToken`. Rejected, failed,
or cancelled work returns no result.

`RasterResult` exposes tightly packed `pixels`, `width`, `height`,
`stride_bytes`, `format`, deterministic `product_id`, `graph_content_id`, exact
`peak_memory_bytes`, `evaluated_nodes`, and `produced_samples`.
`CoverageResult` exposes the same immutable evaluation metadata with
`format == "coverage8"` and one byte per sample.

## Lanczos3 resampling

The public `ferrastra.resample.lanczos3` operation has semantic version 1 and
accepts one premultiplied encoded RGBA8 `source` input. Bind `source_width`,
`source_height`, `destination_width`, and `destination_height` as positive
integer pixel dimensions. The `edge_mode` enum accepts `clamp`, `transparent`,
`reflect`, or `wrap`; its default is `clamp`. The `working_space` enum accepts
`srgb_encoded` or `srgb_linear`; its default is `srgb_linear`.

Destination pixel centers map to source pixel centers. Minification widens the
normalized three-lobe filter support. Regional requests use global destination
coordinates, so independently evaluated tiles are byte-identical to the same
region of a monolithic result. Filtering clamps reconstructed premultiplied
channels to the reconstructed alpha before half-up RGBA8 quantization.

`ferrastra.resample.lanczos3-view` version 1 uses the same numerical contract on
an explicit axis-aligned sampling grid. In addition to source and destination
dimensions it accepts `source_center_x`, `source_center_y`, `source_step_x`, and
`source_step_y`, making exact viewport phase and non-power-of-two zoom part of
the product identity.

## Affine resampling

`ferrastra.resample.affine-bilinear` and
`ferrastra.resample.affine-nearest` version 1 accept premultiplied encoded
RGBA8. The six `source_m11`, `source_m12`, `source_m21`, `source_m22`,
`source_tx`, and `source_ty` scalar parameters map destination pixel indices to
source sample coordinates. Bilinear sampling accepts `srgb_encoded` or
`srgb_linear` working space; nearest sampling preserves exact selected bytes.
Both accept `transparent` or `clamp` edge mode and remain byte-identical across
regional partitions.

`ferrastra.resample.coverage-affine` version 1 accepts Coverage8 and the same
affine geometry. Its `filter` is `nearest`, `linear`, or `area`; its `edge_mode`
is `transparent` or `clamp`. `area` performs exact weighted box integration for
axis-aligned minification, preserving the scalar coverage range without color
or photographic-filter behavior.

## Exceptions and metadata

`FerrastraError` is the public base exception. `GraphError`, `EvaluationError`,
and `BufferError` identify the boundary that rejected work. `__version__`
reports the matching Python and embedded native package version.
