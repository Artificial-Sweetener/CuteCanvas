# Assistant Engineering Guidelines

You are contributing to `QPane`, a high-performance production library. Your primary goal is **Stability, Consistency, and Polish**.

**IMPORTANT:** You are bound by the rules in `CONTRIBUTING.md`. Read it. It defines the architectural boundaries, naming conventions, and strict tooling requirements that apply to all contributors, human or AI.

## 1. The Prime Directive: Production Quality
*   **Stability > Velocity:** Prioritize robust, safe code over quick fixes.
*   **Zero Debt:** Never commit `print()` statements, commented-out code, or temporary `TODO`s.
*   **Graceful Failure:** The application must never crash. Handle errors at the appropriate boundary.

## 2. Architecture & Separation of Concerns
The `QPane` widget is a **Facade**. Keep it thin: public widget methods validate
inputs, preserve the public contract, and delegate to the owner of the concern.

### Architecture Guidance Is Living
The architecture guidance below describes QPane's current ownership map. It is
not a freeze on future structure.

When reassessment shows that a concern belongs somewhere else, update this
architecture section in the same change that moves the boundary. Do not preserve
an outdated boundary because it is documented here.

Update this section only when ownership or dependency boundaries change, such as
when a concern gains a new authoritative owner, a subsystem is split or
extracted, or a new architectural layer becomes part of the intended design.

### Ownership Reassessment Before Editing
Before extending an existing class, module, subsystem, or workflow, reassess
whether the current owner is still the correct owner for the concern being
changed.

Do not assume the existing location is correct because related code is already
there. Identify the concern, its authoritative owner, and the dependency
direction before editing.

If the change introduces a distinct responsibility, change cadence, state owner,
collaboration boundary, or public/private API boundary, split or extract that
responsibility as part of the change instead of deferring cleanup.

If behavior spans multiple components, trace the current ownership and data flow
before editing. Prefer correcting the ownership model over layering
compensating patches across consumers.

Place new code by ownership and dependency direction, not convenience,
proximity, or minimal diff size.

### Object-Oriented Ownership
Use strict object-oriented design for stateful behavior and system
collaboration. A class, service, controller, presenter, or domain object that
owns state must also own the behavior that mutates, interprets, validates, or
coordinates that state.

Collaborators should communicate through explicit public methods, protocols, or
injected dependencies. Do not reach into private collaborator attributes or
duplicate another component's state, geometry, lifecycle, cache policy, input
policy, rendering rules, or workflow rules.

Stateless helper functions and value types are acceptable only when they clarify
ownership and do not hide responsibilities that belong to a stateful owner.

### DRY Means Single Ownership
Favor DRY when it reduces repeated change risk, but do not create abstractions
that obscure ownership or intent.

The most important duplication to remove is duplicated responsibility. State,
geometry, lifecycle, cache policy, input policy, rendering rules, and workflow
rules must have one authoritative owner.

Other components may observe, delegate to, adapt, or cache derived results from
that owner, but must not re-implement the concern in parallel. If multiple
components need the same behavior, move it to the owner or extract a new owner
with an explicit boundary.

### Current Ownership Map
The current ownership map is:

*   **Core (`qpane/core/`)**: `QPaneState` owns lifecycle, configuration application, and feature installation. `Config` owns settings. `FeatureRegistry` owns plugin registration. System headroom observation runs through the shared executor and returns immutable samples so automatic cache policy never queries the operating system on the GUI thread.
*   **Catalog (`qpane/catalog/`)**: `Catalog` owns host-facing image identity, paths, and navigation. `CatalogController` and `ImageCatalog` own catalog mutation and bookkeeping.
*   **Composition (`qpane/composition/`)**: `CompositionService` owns independent documents: stable identity, canvas bounds, descriptive origin, browser order, active selection, document policy, comparison state, and detached snapshots. `LegacySceneCompositionAdapter` validates and projects the public catalog-scene compatibility values into that document model, while the focused public-policy mapper is the single translation boundary between host and domain permission values. Catalog navigation creates or addresses documents through compatibility workflows but does not own a second scene model. `CompositionLayerStore` is the one composition-keyed owner of every ordered layer instance, including seeded images, and publishes coherent stack mutations only after its document record is complete. Typed domain source references separate reusable resource identity from independent instance identity and presentation, while typed effect references retain non-destructive source-backed effects. `CompositionLayerEditService` owns generic undoable add, remove, duplicate, atomic instance replacement, and atomic ordered-stack transitions, including tree reorder, without knowing source or effect domains. `CompositionResourceLifetime` owns live, session, and history leases for instance and effect resources and routes final release to registered domain lifecycle owners. `CompositionEditHistory` is the sole chronological, byte-budgeted undo/redo store for placement, selection, mask, editable-raster, vector, and layer-lifecycle commands; it releases retained resource leases and publishes release callbacks when branches are discarded or evicted. `CompositionEditController` routes commands to their domain handlers and publishes scope-level history availability after every chronology change.
*   **Scene (`qpane/scene/`)**: Internal scene descriptors, typed layer-source and layer-effect references, cross-kind assembly, derived placement, interaction and hit-test metadata, scene/layer identity, focused source/effect capability registries, and internal mutation routing. Composition references pass directly into scene descriptors; no parallel closed scene-source union exists. Metadata, raster presentation, vector presentation, content hit testing, coverage, detached-pixel presentation, and effect rendering have separate exact-type registries, so a domain implements only capabilities it owns. `SceneLayerAssetKey` identifies one placed instance while `SourceRenderAssetKey` identifies reusable source products independently of geometry. `RasterBounds` owns integer source-local extents. Immutable six-coefficient `LayerTransform` is the sole affine local-to-scene mapping; placement is its derived axis-aligned bound. `AffineTransformGeometry` owns eight-handle scale, rotation, and affine skew math. `SceneLayerTransformPreview` owns transient render-only transforms, `SceneLayerTransformController` owns cumulative unresolved whole-layer sessions against source-owned content bounds, and exact transform edits own history replay. Move delegates translation to that same controller and preserves unresolved previews across temporary tool changes. `RasterLayerMutationCoordinator` routes generic raster policy and bounds requests to source-domain owners. `LayerPixelOwnerRegistry` is the sole mapping from editable layer sources to pixel owners, which expose content occupancy and mutations through one generic contract, while `LayerPixelMutationCoordinator` routes selection-constrained requests through it. `SceneLayerSelectionController` owns stable generic layer selection. Immutable selected-pixel preview values cross into rendering without owning raster state.
*   **Coverage (`qpane/coverage/`)**: `CoverageSurface` owns authoritative 8-bit grayscale coverage pixels on the shared sparse 512-pixel tile grid, logical extent policy, synchronized region access, algebra, clipped compatibility snapshots, and content/structure revisions. Fixed, expand-on-write, and behaviorally unbounded layers use one storage and mutation path; transparent gaps allocate nothing. It is source-neutral storage shared by masks and pixel selections. `AffineCoverageResampler` adapts that storage to the shared raster affine-resampling owner without duplicating interpolation policy.
*   **Painting (`qpane/painting/`)**: Immutable presets, rich pointer samples, deterministic dab expansion, input smoothing, and shared color/coverage compositing define one brush engine for every paint-capable target. `PaintingCoordinator` owns active target selection and exact transaction routing; `BrushSourceCoordinateSession` preserves layer-local stroke continuity when expandable raster storage changes its zero-origin source coordinates. Typed target owners retain their domain's authoritative pixels and history. `BrushTipCache` owns byte-bounded procedural tip products and participates in the shared cache budget. Painting retains source resources with session leases so navigation or layer removal cancels provisional work before final release.
*   **Selection (`qpane/selection/`)**: `PixelSelectionService` is the authoritative owner of composition-scoped pixel-selection coverage and its edit commands. Selection geometry, composition algebra, layer projection, and cached boundary extraction remain independent of masks and editable raster sources.
*   **Raster (`qpane/raster/`)**: `SparseRasterGrid` is the one zero-default tiled storage authority used by coverage and premultiplied RGBA surfaces; its stable local coordinates, sparse snapshots, and reframe operation prevent off-canvas gaps from becoming allocations. `EditableRasterAssetStore` owns editable premultiplied RGBA assets. Raster descriptor and source-resolver owners adapt those assets into generic scene layers, while `EditableRasterPresentationState` marks live transactions volatile so pointer samples bypass derived products and settled revisions return to shared pyramids. `EditableRasterPixelMutationOwner` applies selection-constrained pixel edits, and `EditableRasterStructureMutationOwner` exclusively coordinates asynchronous sparse bounds changes and their composition-history commands. `AffineImageResampler` is the common Qt image projection boundary used by raster fragments, coverage adapters, and other affine-derived image products.
*   **Editor (`qpane/editor/`)**: `EditorCompositionRoot` owns construction order and cross-domain registration for the always-on editor graph; it returns typed collaborators to the facade and owns no document state. `EditorOperationResolver` is the sole decision boundary for Move, Transform, Paint, Delete, and selection intent: it combines intrinsic source capabilities, per-layer interaction policy, composable host policy, current selection/floating state, pointer context, stable denial reasons, and explicit alternatives. Tools, facade commands, and demo controls consume that resolution instead of duplicating source-kind rules. `EditorInteractionCoordinator` coordinates source-neutral layer selection, pixel selection, canvas-clipped source-coverage projection, selection-constrained deletion, and mask-stroke constraints by delegating to the authoritative scene, selection, and source-domain owners. `LayerSelectionProjectionCache` retains revision-keyed exact layer-local derivatives so transformed selection movement does not repeatedly resample authoritative scene coverage. `SelectedPixelMoveTargetResolver` intersects that projection with owner-supplied content occupancy and owns movement eligibility. `FloatingPixelSession` owns one unresolved cut/copy affine transform around an immutable lift; translation is its integral fast path. `SelectedPixelMovementController` coordinates Move and Transform input without parallel sessions, while `FloatingPixelResolutionOwner` settles the affine result once to its source, a compatible destination, or a new transform-preserving layer. `FloatingLayerPromotionRegistry` routes created-layer lifecycle to mask and editable-RGBA domain owners, while `FloatingPixelHistory` replays every raster, selection, selected-layer, and created-layer transition as one command. `EditorMovementInteraction` and `EditorTransformInteraction` give active pixel selection strict priority over whole-layer geometry and separate temporary input suspension from explicit cancellation. These components own no duplicate durable scene or pixel state.
*   **Rendering (`qpane/rendering/`)**: `SceneAssembly` owns complete ordered scene construction. `SceneRenderCompiler` compiles metadata and source identity without requiring pixels, routes only raster or vector primitives, and owns provider-revision invalidation plus compiled hit-test metadata. `RasterRenderProductStore` is the single revision-aware LOD boundary for catalog images, editable rasters, placed assets, and masks: it requests shared pyramids, invalidates source tiles, retains byte-budgeted pending previews and source-owned sparse display samples, and yields to completed products. `RasterRenderPlanner` applies that policy and emits the sole raster primitive, including finite visible patch batches whose clipped cores retain filter bleed; dense visible tile sets use one display-bounded sample instead of one pyramid per patch. Volatile live samples bypass derived products without creating a mask renderer. `VectorRenderPlanner` remains the semantic sampler for immediate pictures or complete refined tile batches. `SceneItemCompositor` draws ordered raster and vector primitives and isolates all raster patches for a floating edit as one logical layer, while renderer-owned floating-product damage and durable handoff make partial repair independent of source kind. `VectorRenderWorkCoordinator` owns latest-only asynchronous visible refinement, and `VectorTileCache` owns scale/DPR-keyed byte-bounded products under shared cache coordination. `LayerEffectFrameCompiler` adapts typed target-local effects into render-source clips before drawing and hit testing. `LayerRasterizer` owns explicit smooth premultiplied raster output for non-destructive source conversion. `SceneRenderHitTester` owns inverse-affine render-item intersection and clip-coordinate projection. `RenderingPresenter` coordinates these owners with widget paint and overlay orchestration. Pyramid, sample, and tile payload caches use `SourceRenderAssetKey`; instance damage and durable handoff use `SceneLayerAssetKey`, so explicitly shared sources reuse products across compositions without coupling geometry. `Viewport` owns persistent pan/zoom state, transforms, coordinate conversion, and authoritative constraints. `ViewportMotionController` owns transient kinetic translation and its timer lifecycle. Visibility planning owns layer-visible source geometry used to cull tile work before painting.
*   **Tools (`qpane/tools/`)**: `ToolInteractionDelegate` owns widget plumbing, tool activation, and OS-cursor arbitration. `ToolActivationPorts` supplies focused typed cursor, navigation, movement, transform, pixel-selection, painting, and smart-selection boundaries to built-ins; only custom `ExtensionTool` activation receives the frozen compatibility mapping projection. The pointer-input subsystem owns Qt mouse/touch/tablet normalization, physical-modality transitions, application-level pen proximity, sequence capture, synthesized-mouse rejection, gesture arbitration, palm rejection, touch navigation geometry, and routing from declarative `ToolInputProfile` capabilities. Tool classes own tool-specific gesture translation; `MoveTool` supplies constrained pointer gestures and keyboard nudges to the editor movement boundary without owning selection, pixels, or scene state. `TransformTool` maps the eight handles, body, rotation band, Photoshop modifier policy, explicit commit/cancel, and temporary suspension onto the focused editor transform port; it owns no geometry or durable pixels. `BrushTool` translates mouse and normalized rich-pointer input into painting-owned stroke sessions and owns only immediate feedback; `BrushPreviewRenderer` owns its canvas overlay.
*   **Masks (`qpane/masks/`)**: `MaskAssetStore` owns mask IDs and binds them to shared coverage surfaces. Mask edit owners produce atomic commands for the composition history but do not own an independent undo stack. `MaskEditService` owns transactional pixel edits and async epochs, while `MaskGeneratedEditService` owns generated-mask application. `MaskStrokeRegionPlanner` maps semantic local brush geometry into writable storage, `DecimatedStrokePreview` owns incremental selection-constrained preview construction, and `MaskStrokePipeline` owns worker submission and stroke commit ordering. `MaskRenderCache` and `MaskRasterizer` own colorized native presentation, live sampled products, density-hysteretic sampled reuse, and render metrics; they do not own scene planning, pyramids, or tiles. Worker derivation is detached and only `MaskRenderWorkCoordinator` promotes results through the UI-owned cache boundary. `MaskPixelRenderSynchronizer` maps durable local pixel patches into storage-aligned cache refreshes. `MaskLayerCoordinator` adapts composition-owned layer instances and scene mutation routing; `MaskLayerWorkflow` coordinates import, creation, removal, and stack commands without owning pixels, order, or presentation state. `MaskActivationController` owns editable-mask activation, `ActiveMaskLayerCoordinates` maps editing through the resolved mask transform, `MaskCanvasProjectionService` owns viewport-independent authoring/canvas mapping, and `MaskRasterMutationOwner` implements generic asynchronous raster bounds work. `MaskAutosaveCoordinator` owns autosave installation and signals while projection, encoding, and I/O run on its worker boundary. `MaskService` is the host-facing feature facade that wires and delegates to these owners. `MaskComponentAdjustmentTool` owns reusable component grow/shrink behavior consumed by the factory SAM tool. `MaskSourceCapabilities` supplies only mask metadata, raster presentation, volatility, content hit testing, coverage, and detached-pixel presentation through focused registries.
*   **Placed assets (`qpane/placed/`)**: `PlacedAssetStore` owns embedded or linked source provenance, decoded fallback pixels, status, generations, and content revisions shared by independent layer instances. `PlacedAssetWorkflow` coordinates asynchronous link creation, refresh, relink, embed, and exact history; stale work cannot publish. `PlacedAssetRasterizationService` delegates pixel production to rendering and atomically replaces an instance with an editable-raster source. Descriptor, capability, lifecycle, and mutation owners adapt this domain into the generic scene and composition boundaries.
*   **Vector (`qpane/vector/`)**: `VectorAssetStore` owns immutable semantic document revisions with stable object IDs, paths, parametric shapes, semantic Unicode text, styles, and object transforms. `VectorEditService` owns atomic document commands, `VectorObjectSelectionController` owns object selection, `VectorNodeEditController` owns durable-base node sessions, and `VectorTextEditController` owns durable-base in-place text sessions and contextual character/paragraph policy. `SemanticTextLayoutCache` owns byte-bounded Qt-shaped pictures, exact glyph geometry, carets, and fallback diagnostics as distinct derivatives; the stateless text-path builder produces detached color-preserving outline documents without owning chronology or scheduling. `VectorDocumentProjection` is the sole transient semantic presentation owner shared by visible vectors and attached vector masks; focused tools translate gestures and detached UI renderers draw node/text feedback without owning documents. Source capabilities adapt vector documents into the shared scene; `VectorConversionService` is the one generation-controlled worker lifecycle for pixel-selection, editable-raster, and text-path conversions, including resource leases, cancellation, stale-result rejection, authoritative commit, and terminal publication. `VectorMaskEffect` references the same semantic source on any target layer, `VectorAuthoringTargetResolver` gives visible vector layers and attached masks one editing boundary, `VectorMaskPathCache` incrementally derives exact byte-bounded union geometry, `VectorRenderCache` reuses ordered stable picture segments around active object previews, and focused tile owners render each bounded visible batch once before slicing exact cached cores so complex durable presentation never blocks the GUI thread.
*   **Persistence (`qpane/persistence/`)**: Private versioned composition archives capture, validate, atomically encode, and transactionally restore composition-owned layer instances plus mask, editable-RGBA, placed-asset, vector, and semantic-text authoring state, including sparse off-canvas pixels, extent policies, provenance, optional linked fallback pixels, source-backed effects, Unicode, character spans, paragraph policy, and requested font chains. Version 7 stores deduplicated resources separately from their independent instances and effects and encodes coverage/RGBA tiles without materializing transparent gaps; the reader migrates versions 2 through 6. This boundary is intentionally not part of the public host API yet.
*   **SAM (`qpane/sam/`)**: `SamManager` owns predictor lifecycle and checkpoint readiness. SAM inference belongs behind the SAM service boundary.
*   **Compare (`qpane/compare/`)**: `CompareService` owns catalog-backed compare scene contributions and delegates comparison source selection, split state, and source revisions to the active composition.
*   **Swap (`qpane/swap/`)**: `SwapCoordinator` owns navigation-time swap, prefetch, cancellation, and pending-work orchestration.
*   **Cache (`qpane/cache/`)**: `CacheCoordinator` owns cache budgeting and consumer coordination.
*   **Concurrency (`qpane/concurrency/`)**: `TaskExecutor` owns heavy/background work, retry policy, and scheduling. **Never block the UI thread.**
*   **UI (`qpane/ui/`)**: Qt-only helpers own widget plumbing, drag/drop, clipboard, diagnostics presentation, operation-oriented transform cursors, and cached rendering of detached editor feedback such as hover outlines, marching ants, and the constant-screen-size eight-handle transform box; they do not own selection, geometry, or layer state.

### Structural Change Rules
For behavior-critical areas, work in two steps:

1. Add characterization or regression tests for existing behavior.
2. Perform structural changes behind those tests.

Do not start structural changes in an area without behavior safeguards for that
area.

Prefer clean replacement over internal compatibility layers. Structural changes
must be complete: update callsites, remove dead code, remove temporary bridges,
and leave the codebase looking as if the new design was the original design.

Prefer vertical slices that land safely over large unverified rewrites. If
behavior changes are intentional, call them out explicitly and test them as new
behavior.

## 3. The Trinity: Consistency is Mandatory
The "Trinity" ensures the Public API is consistent across four pillars. **When one changes, they ALL change.**

0.  **Contract (`qpane.pyi`):** The frozen public API definition.
1.  **Implementation (`qpane.py`):** The code itself.
2.  **Documentation (`docs/`):** The user manuals.
3.  **Demonstration (`examples/`):** The tutorialized proof-of-concept.

**Rule:** You must update all four in the same turn. Never leave the demo or docs "for later."

**Demo Style:** Demos must be "tutorialized"—clean, readable code that teaches the user how to use the new feature (see `examples/demonstration/`).

**Strict Constraint:** Demos must rely *exclusively* on the public API defined in `qpane.pyi`. Never reach into private internals (`_underscore_methods`) from example code.

**Docs Guardrail:** Documentation is for host developers using the public facade. Describe only supported API and behaviors; never mention internal wiring or unsupported swaps (e.g., replacing managers). Every public symbol must have a concise explainer in `docs/api-reference.md` and tutorialized coverage in the relevant narrative guide; bare symbol lists do not satisfy the guide standard.

## 4. Compatibility & Refactoring Strategy
We distinguish strictly between the **Public API** and the **Internal Implementation**.

### Public API: Frozen & Sacred
Defined by `qpane.pyi` and `qpane/__init__.py`.
*   **Rule:** **NEVER** break the public contract.
*   **Verification:** The "Trinity" check ensures `qpane.py` (impl), `qpane.pyi` (stub), and `docs/` align.
*   **Changes:** If you must change the public API, you must update the stub (`.pyi`), documentation (`docs/`), and demonstration (`examples/`) in the same turn.

### Internal Implementation: Fluid & Clean
Internal modules (`qpane.core`, `qpane.masks`, etc.) are **NOT** subject to backward compatibility rules within the library.
*   **Rule:** Refactor ruthlessly for quality while following the ownership reassessment rules above.
*   **NO SHIMS:** Do not leave backward-compatibility shims (e.g., `def old(): return new()`) in internal code.
*   **Complete Refactors:** If you change an internal signature, you **MUST** find and update **ALL** internal callers immediately.
*   **Outcome:** The codebase should look as if the new design was the original design.
*   **Architecture Updates:** If the refactor changes the ownership map or dependency boundaries, update the architecture guidance in this file in the same change.

## 5. Coding Standards
*   **Type Hints:** Mandatory for all new code. Use `typing.TYPE_CHECKING` to avoid circular imports.
*   **Docstrings:** Mandatory.
    *   *Public:* Google-style sections (`Args:`, `Returns:`, `Side effects:`).
    *   *Internal:* Concise summary.
*   **Self-Documenting Code:**
    *   **Code tells the "What":** Logic should be clear enough to read like a sentence. If a block is complex, extract it into a named method.
    *   **Comments:** Use *only* for non-obvious logic or complex constraints. Docstrings and naming should cover the rest.
*   **Naming:**
    *   *Principle:* **Precise and Self-Documenting.** Names should be unambiguous but concise. Avoid generic terms (`data`, `obj`) and cryptic abbreviations.
    *   Public Widget Methods: `camelCase` (matches Qt).
    *   Internal Logic/Helpers: `snake_case` (standard Python).
    *   Enums: `PascalCase` classes, `UPPER_CASE` members.
*   **Module Layout:**
    *   **Preamble:** Docstring -> Imports -> Logger.
    *   **Public Interface:** Constants -> Enums -> Exceptions.
    *   **Implementation:** Main Classes/Functions first.
    *   **Internals:** Private helpers last.
*   **Class Layout:**
    *   **Public First:** `__init__` -> Public Methods -> Properties.
    *   **Group by Intent:** Keep related logic together (e.g., all Zoom methods).
    *   **Internals Last:** Private methods at the bottom.
*   **The Banner (`qpane.py` ONLY):**
    *   Public methods **ABOVE** the `# Internal Implementation` banner.
    *   Internal methods **BELOW** the banner.
    *   **Note:** Do not use this banner pattern in any other module.

## 6. Drafting Commit Messages
**Only commit when explicitly asked.**
When asked to commit, use the Conventional Commits standard so the scope of the change is clear and release automation can infer the correct version impact.

Format: `type(scope): subject`
*   `feat`: New feature (Minor bump).
*   `fix`: Bug fix (Patch bump).
*   `docs`: Documentation only.
*   `style`: Formatting/whitespace.
*   `refactor`: Code change that neither fixes a bug nor adds a feature.
*   `perf`: Performance improvement.
*   `test`: Adding/fixing tests.
*   `chore`: Build/tooling changes.
*   **BREAKING CHANGE:** Append `!` (e.g., `feat(api)!:`) for Major bump.

## 7. Verification (The Safety Net)
You must run the same checks as the git hooks before reporting success. Always run these in the `.venv`.

1.  **Format & Lint:**
    ```powershell
    .venv\Scripts\python -m ruff check --fix .
    .venv\Scripts\python -m black .
    ```
2.  **Project Tools (Mandatory):**
    ```powershell
    .venv\Scripts\python tools\fix_encoding.py
    .venv\Scripts\python tools\check_docstrings.py
    .venv\Scripts\python tools\check_api_order.py
    .venv\Scripts\python tools\check_consistency.py
    .venv\Scripts\python tools\add_license_headers.py
    ```
3.  **Test (Parallelized):**
    ```powershell
    .venv\Scripts\python -m pytest -n auto
    ```
    **Note:** Allow a longer timeout for this command in automation/harness runs so the
    parallel suite can complete cleanly.
    **Do not ignore failures.** If tests fail, fix them.
