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

*   **Core (`qpane/core/`)**: `QPaneState` owns lifecycle, configuration application, and feature installation. `Config` owns settings. `FeatureRegistry` owns plugin registration.
*   **Catalog (`qpane/catalog/`)**: `Catalog` owns host-facing image identity, paths, and navigation. `CatalogController` and `ImageCatalog` own catalog mutation and bookkeeping.
*   **Composition (`qpane/composition/`)**: `CompositionService` owns public composition records, browser order, generated default image compositions, layered scene composition records, active composition selection, and composition-scoped comparison state. `ImageSceneLayerStore` owns all composition layer instances and their cross-kind z-order, visibility, presentation, interaction policy, source-to-scene transforms, and labels. `CompositionEditHistory` is the sole chronological, byte-budgeted undo/redo store for placement, selection, mask, and editable-raster commands; `CompositionEditController` routes those commands to their domain handlers and publishes scope-level history availability after every chronology change.
*   **Scene (`qpane/scene/`)**: Internal scene descriptors, typed layer sources, cross-kind assembly, derived placement, interaction and hit-test metadata, scene/layer identity, provider/resolver contracts, and internal mutation routing. `RasterBounds` owns integer source-local extents, `LayerTransform` maps local coordinates into scene space independently of extent, and `RasterLayerMutationCoordinator` routes generic raster policy and bounds requests to source-domain owners. `LayerPixelOwnerRegistry` is the sole mapping from editable layer sources to pixel owners, which expose content occupancy and mutations through one generic contract, while `LayerPixelMutationCoordinator` routes selection-constrained requests through it. `SceneLayerSelectionController` owns stable generic layer selection, `SceneLayerPlacementPreview` owns transient render-only placement, `SceneLayerMovementController` coordinates policy-checked selection, preview, and movement commits without knowing source domains, and `SceneLayerMovementInteraction` adapts panel coordinates and publication callbacks. Immutable selected-pixel preview values cross into rendering without owning raster state.
*   **Coverage (`qpane/coverage/`)**: `CoverageSurface` owns authoritative 8-bit grayscale coverage pixels, integer local bounds, fixed/expand-on-write policy, synchronized region access, algebra, snapshots, and content/structure revisions. It is source-neutral storage shared by masks and pixel selections.
*   **Selection (`qpane/selection/`)**: `PixelSelectionService` is the authoritative owner of composition-scoped pixel-selection coverage and its edit commands. Selection geometry, composition algebra, layer projection, and cached boundary extraction remain independent of masks and editable raster sources.
*   **Raster (`qpane/raster/`)**: `EditableRasterAssetStore` owns editable premultiplied RGBA assets. Raster descriptor and source-resolver owners adapt those assets into generic scene layers, `EditableRasterPixelMutationOwner` applies selection-constrained pixel edits, and `EditableRasterStructureMutationOwner` exclusively coordinates asynchronous bounds changes and their composition-history commands.
*   **Editor (`qpane/editor/`)**: `EditorInteractionCoordinator` coordinates source-neutral layer selection, pixel selection, source-coverage projection, selection-constrained deletion, and mask-stroke constraints by delegating to the authoritative scene, selection, and source-domain owners. `LayerSelectionProjectionCache` retains revision-keyed exact layer-local derivatives so transformed selection movement does not repeatedly resample authoritative scene coverage. `SelectedPixelMoveTargetResolver` intersects that projection with owner-supplied content occupancy and owns movement eligibility. `FloatingPixelSession` owns unresolved cut/copy displacement and pointer state around an immutable lift plus the exact source-neutral transition for its current displacement. `SelectedPixelMovementController` coordinates input, transition composition, and explicit resolution, while `FloatingPixelResolutionOwner` applies source, compatible-destination, or new-layer outcomes. `FloatingLayerPromotionRegistry` routes created-layer lifecycle to mask and editable-RGBA domain owners, while `FloatingPixelHistory` replays every raster, selection, selected-layer, and created-layer transition as one command. `EditorMovementInteraction` gives active pixel selection strict priority over whole-layer placement and separates temporary input suspension from explicit cancellation. These components own no duplicate durable scene or pixel state.
*   **Rendering (`qpane/rendering/`)**: `SceneAssembly` owns complete ordered scene construction. `RenderingPresenter` consumes assembled scenes for draw orchestration and render-work planning. `FloatingPixelRenderCompiler` adapts exact source-neutral pixel transitions through the owning layer-source resolver into one render contribution, and `Renderer` retains that contribution until the matching durable source revision presents identical pixels. Layer-source resolvers exclusively own canonical-pixel presentation, including mask colorization. `Viewport` owns persistent pan/zoom state, transforms, coordinate conversion, and authoritative constraints. `ViewportMotionController` owns transient kinetic translation and its timer lifecycle. Visibility planning owns layer-visible source geometry used to cull tile work before painting.
*   **Tools (`qpane/tools/`)**: `ToolInteractionDelegate` owns widget plumbing, tool activation, and OS-cursor arbitration. The pointer-input subsystem owns Qt mouse/touch/tablet normalization, physical-modality transitions, application-level pen proximity, sequence capture, synthesized-mouse rejection, gesture arbitration, palm rejection, touch navigation geometry, and routing from declarative `ToolInputProfile` capabilities. Tool classes own tool-specific gesture translation; `MoveTool` supplies constrained pointer gestures and keyboard nudges to the editor movement boundary without owning selection, pixels, or scene state. `BrushStrokeSession` owns captured brush-contact state and segment formation without owning mask persistence. `BrushTool` owns semantic brush-feedback state, while `BrushPreviewRenderer` owns its canvas rendering without owning input policy or mask persistence.
*   **Masks (`qpane/masks/`)**: `MaskAssetStore` owns mask IDs and binds them to shared coverage surfaces. Mask edit owners produce atomic commands for the composition history but do not own an independent undo stack. `MaskEditService` owns transactional pixel edits and async epochs, while `MaskGeneratedEditService` owns generated-mask application. `MaskStrokeRegionPlanner` maps semantic local brush geometry into writable storage, `DecimatedStrokePreview` owns incremental selection-constrained preview construction, and `MaskStrokePipeline` owns worker submission and stroke commit ordering. `MaskRenderCache` and `MaskRasterizer` own derived overlay rasters, cache policy, and render metrics, while `MaskRenderWorkCoordinator` owns asynchronous render scheduling, cancellation, and completion. `MaskPixelRenderSynchronizer` maps durable local pixel patches into storage-aligned cache refreshes. `MaskLayerCoordinator` adapts composition-owned layer instances and scene mutation routing; `MaskLayerWorkflow` coordinates import, creation, removal, and stack commands without owning pixels, order, or presentation state. `MaskActivationController` owns editable-mask activation, `ActiveMaskLayerCoordinates` maps editing through the resolved mask transform, `MaskCanvasProjectionService` owns viewport-independent authoring/canvas mapping, and `MaskRasterMutationOwner` implements generic asynchronous raster bounds work. `MaskAutosaveCoordinator` owns autosave installation and signals while projection, encoding, and I/O run on its worker boundary. `MaskService` is the host-facing feature facade that wires and delegates to these owners. `MaskComponentAdjustmentTool` owns reusable component grow/shrink behavior consumed by the factory SAM tool. `MaskLayerSourceResolver` supplies mask coverage through the generic scene resolver registry.
*   **Persistence (`qpane/persistence/`)**: Private versioned composition archives capture, validate, atomically encode, and transactionally restore composition-owned layer instances plus mask and editable-RGBA authoring surfaces, including off-canvas pixels and extent policies. This boundary is intentionally not part of the public host API yet.
*   **SAM (`qpane/sam/`)**: `SamManager` owns predictor lifecycle and checkpoint readiness. SAM inference belongs behind the SAM service boundary.
*   **Compare (`qpane/compare/`)**: `CompareService` owns catalog-backed compare scene contributions and delegates comparison source selection, split state, and source revisions to the active composition.
*   **Swap (`qpane/swap/`)**: `SwapCoordinator` owns navigation-time swap, prefetch, cancellation, and pending-work orchestration.
*   **Cache (`qpane/cache/`)**: `CacheCoordinator` owns cache budgeting and consumer coordination.
*   **Concurrency (`qpane/concurrency/`)**: `TaskExecutor` owns heavy/background work, retry policy, and scheduling. **Never block the UI thread.**
*   **UI (`qpane/ui/`)**: Qt-only helpers own widget plumbing, drag/drop, clipboard, diagnostics presentation, and cached rendering of editor feedback such as hover outlines and marching ants; they do not own selection or layer state.

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
