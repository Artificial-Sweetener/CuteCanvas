# Contributing to QPane

Welcome! We're glad you're here.

QPane is a high-performance, CPU-first image viewer designed for production workloads. To maintain this standard, we rely on strict automated tooling and clear architectural boundaries.

This guide explains how to contribute effectively while ensuring the codebase remains healthy, predictable, and production-ready.

## Getting Started

1.  **Create Environment**: Create a virtual environment named `.venv`.

    ```powershell
    python -m venv .venv
    ```

2.  **Activate Environment**: Always work inside the virtual environment.

    ```powershell
    .venv\Scripts\Activate.ps1
    ```

3.  **Install Dependencies**: Install the package in editable mode with dev tools.

    ```powershell
    pip install -r requirements.txt
    ```

4.  **Install Git Hooks**: Run the setup script to configure the safety net.

    ```powershell
    python tools\setup_hooks.py
    ```

    Prefer a single command? Run `python tools\setup_dev.py` to create the venv,
    install dependencies, and install git hooks in one step.

## Architecture & Separation of Concerns

The `QPane` widget acts as a **Facade**, delegating all logic to specialized subsystems. Keep the widget thin: methods should validate inputs and forward them immediately.

### Core Infrastructure (`qpane/core/`)

- **State**: `QPaneState` manages configuration, lifecycle, and feature installation, isolating these concerns from the QWidget. Automatic cache headroom uses the shared executor so operating-system observation cannot block GUI input.
- **Configuration**: [`Config`](docs/configuration.md) objects define the runtime behavior, applied via `QPaneState`.
- **Features**: The `FeatureRegistry` allows optional components (like SAM or Masking) to be injected at runtime.

### The Subsystems

- **Catalog (`qpane/catalog/`)**: Host-facing facade and data model for images, paths, and navigation. [`Catalog`](docs/catalog-and-navigation.md) sequences host mutations; `CatalogController` and `ImageCatalog` own image bookkeeping and collaborate with the rendering-owned pyramid service.
- **Composition (`qpane/composition/`)**: `CompositionService` owns independent document identity, canvas bounds, descriptive origin, document policy, comparison state, active selection, detached browser snapshots, and coherent layer-stack publication. `LegacySceneCompositionAdapter` projects public catalog-scene compatibility values into this model, and the public-policy mapper is the single host/domain permission translation boundary. Catalog navigation remains another document adapter rather than a parallel model. `CompositionLayerStore` owns every composition-keyed layer instance and cross-kind order, including ordinary seeded image layers, while `CompositionLayerEditService` owns generic undoable lifecycle and atomic instance-replacement transitions. Typed source references and `CompositionResourceLifetime` own shared resource identity and live/session/history reachability. `CompositionEditHistory` is the sole chronological, byte-budgeted undo/redo store for editor commands, releases retained resource leases on eviction, and `CompositionEditController` routes commands to domain handlers and publishes scope-level history availability after chronology changes.
- **Scene (`qpane/scene/`)**: Internal scene and layer descriptors carry composition-owned typed source references directly. Separate exact-type registries own metadata, raster presentation, content hit testing, coverage, and detached-pixel presentation; domains implement only capabilities they possess. `SceneLayerAssetKey` identifies instance work and `SourceRenderAssetKey` identifies reusable source products. `RasterBounds` owns integer source-local extents. Immutable six-coefficient `LayerTransform` is the sole affine local-to-scene mapping; placement is derived. Exact transform preview, history, and movement sessions remain source-neutral and survive temporary tool changes. `RasterLayerMutationCoordinator` routes generic raster structure requests, and `LayerPixelOwnerRegistry` is the sole source-to-pixel-owner mapping used for source-domain content occupancy and generic pixel mutation.
- **Coverage (`qpane/coverage/`)**: `CoverageSurface` owns source-neutral 8-bit grayscale coverage on the shared sparse tile grid, logical extent policy, synchronized region access, algebra, clipped snapshots, and content/structure revisions. Fixed, expand-on-write, and behaviorally unbounded layers use one storage path. Its affine projection adapter delegates interpolation to the common raster resampling owner.
- **Painting (`qpane/painting/`)**: Immutable presets, rich samples, smoothing, deterministic dabs, and shared color/coverage compositing form the sole brush engine. `PaintingCoordinator` owns active target and transaction routing, and `BrushSourceCoordinateSession` preserves continuous layer-local geometry across expandable raster storage-origin changes. Typed mask, editable-raster, and pixel-selection adapters mutate their existing authorities. The procedural tip cache is byte-bounded and registered with shared cache coordination; source-backed strokes retain session leases until commit or rollback.
- **Selection (`qpane/selection/`)**: `PixelSelectionService` owns composition-scoped pixel-selection coverage and selection edit commands. Geometry rasterization, coverage composition, layer projection, and cached boundary extraction do not depend on masks or editable raster assets.
- **Raster (`qpane/raster/`)**: `SparseRasterGrid` is the zero-default storage authority shared by coverage and premultiplied RGBA surfaces. `EditableRasterAssetStore` owns RGBA assets. Descriptor and resolver owners adapt them into scenes, while `EditableRasterPresentationState` keeps live transactions off derived products until their settled revision can return to shared pyramids. The pixel-mutation owner applies selection-constrained edits, the structure-mutation owner exclusively coordinates sparse bounds changes and history commands, and `AffineImageResampler` owns shared Qt image projection semantics.
- **Editor (`qpane/editor/`)**: `EditorOperationResolver` is the sole decision boundary for tool, facade, and UI intent; it combines intrinsic capability, layer policy, host policy, current state, stable denial reasons, and explicit alternatives. `EditorInteractionCoordinator` coordinates source-neutral layer selection, pixel selection, canvas-clipped source-coverage projection, selection-constrained deletion, and mask-stroke constraints by delegation. `SelectedPixelMoveTargetResolver` owns movement eligibility. `FloatingPixelSession` owns unresolved pointer and cut/copy displacement state plus the exact transition for its current position, `SelectedPixelMovementController` coordinates input and transition composition, and `FloatingPixelResolutionOwner` applies explicit source, compatible-destination, or new-layer outcomes. `FloatingLayerPromotionRegistry` routes new-layer lifecycle to source domains, and `FloatingPixelHistory` replays every raster, selection, selected-layer, and layer-lifecycle transition atomically. `EditorMovementInteraction` arbitrates that branch ahead of whole-layer placement and distinguishes temporary input suspension from explicit cancellation. None duplicates durable source state.
- **Rendering (`qpane/rendering/`)**: `SceneAssembly` owns complete ordered scene construction. `SceneRenderCompiler` resolves metadata without requiring source pixels. Exact affine frame projection and inverse-affine hit testing are rendering-owned; `RenderingPresenter` coordinates one raster planner plus the semantic vector planner. `RasterRenderProductStore` owns revision-aware pyramid selection, stale tile invalidation, and byte-budgeted pending previews plus sparse display samples shared by catalog, editable, placed, and mask rasters. `RasterRenderPlanner` emits finite overlap-filtered patch batches for sparse sources and one bounded sample for dense visible tile sets. `SceneItemCompositor` draws the closed raster/vector primitive set and isolates all patches participating in one floating edit as one layer. `FloatingPixelRenderCompiler`, renderer-owned product damage, and durable handoff consume source-neutral presentation and keep partial redraws exact. `LayerRasterizer` owns explicit smooth premultiplied output for source rasterization. Source-product caches are independent of instance geometry and reusable across compositions. `Viewport` owns pan/zoom state and transforms. Visibility planning owns layer-visible source geometry used to cull tile work before painting.
- **Tools (`qpane/tools/`)**: `ToolInteractionDelegate` handles widget input and cursor/overlay plumbing. The pointer subsystem routes normalized devices from declarative tool input profiles. [Tool logic](docs/extensibility.md) lives in isolated Tool classes that activate with injected `ToolDependencies`; tools translate gestures and do not own scene or mask state.
- **Masks (`qpane/masks/`)**: `MaskAssetStore` owns mask identities and binds them to shared coverage surfaces. Mask edit owners produce atomic commands for the composition history rather than maintaining a separate undo stack. `MaskEditService` owns transactional edits and async epochs, `MaskGeneratedEditService` owns generated-mask application, and `MaskStrokeRegionPlanner` maps local brush geometry into writable storage. `DecimatedStrokePreview` owns incremental selection-constrained preview construction, while `MaskStrokePipeline` owns worker submission and commit ordering. `MaskRenderCache` owns colorized native and live sampled presentation only; generic rendering owns its LOD, pyramid, tile, composition, and damage policy. `MaskRenderWorkCoordinator` promotes detached worker results through the UI cache boundary, and `MaskPixelRenderSynchronizer` maps durable local edits into storage-aligned cache refreshes. `MaskActivationController` owns editable-mask activation. `MaskCanvasProjectionService` owns viewport-independent authoring/canvas mapping, and `MaskRasterMutationOwner` implements asynchronous mask bounds work. `MaskLayerCoordinator` routes composition-owned layer instances and scene mutations, `MaskLayerWorkflow` owns complete mask lifecycle commands without owning layer order or presentation, and `MaskAutosaveCoordinator` owns autosave wiring while projection, encoding, and I/O run on its worker boundary. [`MaskService`](docs/masks-and-sam.md) is the host-facing facade that wires and delegates to these owners.
- **Placed assets (`qpane/placed/`)**: `PlacedAssetStore` owns embedded and linked provenance, decoded fallback pixels, status, generations, and shared source revisions. `PlacedAssetWorkflow` coordinates asynchronous link creation, refresh, relink, embed, and exact history, while `PlacedAssetRasterizationService` performs an atomic source swap after rendering-owned raster output. Focused descriptor, capability, lifecycle, and mutation owners integrate the domain without parallel scene or history structures.
- **Persistence (`qpane/persistence/`)**: Private versioned composition archives capture, validate, atomically encode, and transactionally restore deduplicated resources and independent composition instances plus mask, editable-RGBA, placed-asset, vector, and semantic-text authoring state. Version 7 preserves sparse off-canvas coverage and RGBA tiles without materializing transparent gaps, and versions 2 through 6 migrate through the current reader. Persistence is not exposed through the host-facing facade yet.
- **SAM (`qpane/sam/`)**: MobileSAM lifecycle and predictor management. `SamManager` handles background predictor preparation; inference is invoked via `qpane/sam/service.py` by the mask workflow.
- **Compare (`qpane/compare/`)**: Catalog-backed comparison workflow state, split settings, source revisions, and compare scene contributions.
- **Swap (`qpane/swap/`)**: Navigation/prefetch orchestration for pyramids, tiles, masks, and SAM predictors. `SwapCoordinator` tracks pending work and `SwapDelegate` bridges QPane callbacks.

### UI Components (`qpane/ui/`)

- **Helpers**: Reusable Qt-focused helpers ([overlays](docs/extensibility.md), drag-and-drop, clipboard) that keep the main `QPane` class free of boilerplate. Editor overlays render cached hover outlines and marching ants without owning selection or layer state.

### Cross-Cutting Rules

- **Concurrency**: Heavy lifting belongs in `TaskExecutor` (in `qpane/concurrency/`), never the UI thread.
- **Caching**: Register with `CacheCoordinator` (in `qpane/cache/`) instead of allocating unbounded memory.
- **Diagnostics**: Use the [`Diagnostics`](docs/diagnostics.md) broker to report internal state for the debug overlay.

## Public API Consistency

This project is built around a single source of truth for its public interface: **`qpane.pyi`**. This stub file defines the official API contract.

The "Trinity" check (`tools/check_consistency.py`) ensures that the Public API is consistent across three pillars:

1.  **The Implementation**: The code (in `qpane.py`) must implement every symbol defined in the contract.
2.  **The Documentation**: The `docs/` folder must document every public symbol, and *only* the public symbols.
    *   *Note:* `configuration-reference.md` is also checked to ensure it matches the actual defaults in `qpane.core.config.Config`.
3.  **The Demonstration**: The `examples/` folder must rely *exclusively* on the public API defined in the contract.

**The `qpane.pyi` file is the anchor. To pass the consistency check, the Implementation, Documentation, and Demonstration must all agree with the stub—and therefore with each other.**

## Code Organization

We follow a strict physical layout in `qpane.py` and other modules to keep code predictable.

### The Banner (`qpane.py` Only)

In `qpane.py` (and **only** `qpane.py`), there is a comment: `# Internal Implementation`.

*   **Above**: Public API methods (must match `qpane.pyi`).
*   **Below**: Internal implementation details (hidden from `qpane.pyi`).

### General Module Layout

We follow a "Public First" layout strategy. Code should be readable from top to bottom, moving from high-level contracts to low-level implementation details.

1.  **Preamble**:
    *   Module docstring explaining *purpose* and *responsibilities*.
    *   Imports: Standard Library -> Third Party -> Local Application.
    *   `TYPE_CHECKING` imports block (keep isolated).
    *   Logger initialization (`logger = logging.getLogger(__name__)`).

2.  **Public Interface**:
    *   Constants and Configuration Defaults.
    *   Enums and Data Structures (Dataclasses, TypedDicts).
    *   Exceptions and Signals.

3.  **Primary Implementation**:
    *   Main classes and public functions.
    *   **Ordering**: Place the most important/central class first.

4.  **Internal Details**:
    *   Private helper functions and internal utility classes.
    *   Implementation details that consumers shouldn't touch.

### Class Structure Guidelines

For complex classes, organize methods by **lifecycle and intent**:

1.  **Lifecycle**: `__init__`, setup, and teardown.
2.  **Public API**: The primary methods callers use.
3.  **Properties**: State accessors.
4.  **Domain Logic**: Group methods by feature (e.g., "Zoom Logic", "Selection Logic").
    *   *Tip:* Within a group, order by flow: `Query` -> `Mutate` -> `Notify/Async`.
5.  **Event Handlers**: Callbacks and signal slots (keep these thin; delegate logic).
6.  **Internals**: Private helpers (`_helper_method`).

### Style Notes

- **Expressive Names**: Let the code explain itself. Inline comments are for non-obvious behavior only.
- **Delegation**: Route interactive state through the interaction layer/delegates. Do not reach into private attributes of collaborators.
- **Grouping**: Keep related helpers together. Do not scatter lifecycle hooks.
- **Enums**: Inherit from `(str, Enum)` instead of `enum.StrEnum` to ensure Python 3.10 compatibility.

## Naming Conventions

We follow a hybrid naming strategy to blend seamlessly with the Qt ecosystem while maintaining Pythonic internals.

*   **Public Widget API (`QPane` class)**: Use `camelCase` for methods and properties. This ensures consistency with the inherited `QWidget` API (e.g., `setFocus`, `update`, `currentImage`).
*   **Signals**: Use `camelCase` (e.g., `imageLoaded`, `zoomChanged`).
*   **Internal Logic & Helpers**: Use `snake_case` (standard PEP 8) for internal implementation details, standalone functions, and non-widget classes (like `Config`).
*   **Enums**: Use `PascalCase` for classes and `UPPER_CASE` for members.

## Typing Philosophy

We adopt a pragmatic, gradual typing approach focused on high-leverage areas. We do not aim for 100% coverage for its own sake, but rather use types as a tool for correctness and developer experience.

1.  **Public API**: All public-facing methods and classes (those exposed in `qpane.pyi`) **must** be fully typed. This ensures a high-quality experience for users in their IDEs and makes the library discoverable.
2.  **Critical Contracts**: We use type hints internally whenever we need to strengthen a contract or make a complex refactor safer. If a function's inputs or outputs are ambiguous, or if a mistake would be costly or hard to debug, add types to enforce the boundary.

*Note: When you add types, ensure they are correct. Incorrect types are worse than no types.*

## Documentation Guidelines

We treat docstrings as the primary reference for behavior. Keep them concise, action-oriented, and proportional to complexity.

### Core Rules

- **Summary**: Lead with a single-sentence, present-tense summary (e.g., "Updates the view," not "Update the view").
- **Spacing**: Add a blank line after the summary if you include additional text.
- **Sections**: Use Google-style sections (`Args:`, `Returns:`, `Raises:`, `Side effects:`) when parameters or behavior are non-obvious.
    - Prefer one-line entries.
    - Only document exceptions callers must handle.
    - Use `Side effects:` for signaling, caching, async work, or thread hops.
- **Redundancy**: Do not restate types already in annotations. Focus on intent and contracts.
- **Inline Comments**: Avoid them. Code should be self-documenting; use comments only to call out non-obvious behavior.
- **Style**: Match Qt/PySide ergonomics (concise, camelCase-aware).

### When to Use Sections

- **Required**: Complex APIs, lifecycle hooks, and methods with non-obvious side effects.
- **Skip**: Simple accessors, pass-through delegates, and methods where the summary is sufficient.

### Coverage Expectations

- **Every** module, class, function, and method must have a docstring.
- **Properties** should document the observable value, not internal storage.
- **Modules** should state their architectural role.

### Examples

**Simple delegate**

```python
"""Expose the current overlay registry owned by the interaction layer."""
```

**Complex/public API**

```python
"""Primary API for displaying a new image in the qpane.

Args:
    image: Non-null image to display.
    source_path: Optional filesystem path for metadata/drag.
    fit_view: Fit the image to the viewport when True.

Raises:
    ValueError: If `image` is null.
Side effects:
    Queues pyramid rebuilds and emits imageLoaded.
"""
```

## The Commit Hook: Your Safety Net

When you run `git commit`, our hooks run a battery of checks. If they fail, your commit is rejected. This is by design.

*   **Auto-Formatting**: `ruff` and `black` will automatically format your code.
*   **Encoding Check**: Ensures all files are valid UTF-8.
*   **Docstring Check**: Fails if *any* module, class, or function is missing a docstring.
*   **License Header Check**: Automatically adds or updates the GPLv3-or-later license header.
*   **Tests**: Runs the full test suite.
*   **API Order Check**: Fails if public methods (from `.pyi`) are below the `# Internal Implementation` banner in `qpane.py`, or if internal methods are above it.
*   **Consistency Check**: Fails if the "Trinity" is out of sync.

## Commit Messages & Versioning

We use **Semantic Versioning** and **Conventional Commits** to automate our release process. Your commit messages determine the next version number.

### The Rules

The `commit-msg` hook will reject any commit that does not follow the Angular convention:

```text
type(scope)!: subject
```

#### 1. Type

The `type` must be one of the following:

*   **`feat`**: Introduces a new feature.
    *   *Use when:* Adding a new capability to the widget or API.
    *   *Example:* `feat(sam): add auto-segmentation support`

*   **`fix`**: Patches a bug in the codebase.
    *   *Use when:* Fixing a crash, logic error, or UI glitch.
    *   *Example:* `fix(ui): resolve flicker on resize`

*   **`docs`**: Documentation only changes.
    *   *Use when:* Updating docstrings, markdown files, or comments.
    *   *Example:* `docs: update installation guide`

*   **`style`**: Changes that do not affect the meaning of the code.
    *   *Use when:* Fixing formatting, whitespace, or linting issues (often handled by `ruff`/`black`).
    *   *Example:* `style: reformat with black`

*   **`refactor`**: A code change that neither fixes a bug nor adds a feature.
    *   *Use when:* Restructuring code, renaming variables, or simplifying logic without changing behavior.
    *   *Example:* `refactor(core): extract config logic to separate class`

*   **`perf`**: A code change that improves performance.
    *   *Use when:* Optimizing rendering, memory usage, or startup time.
    *   *Example:* `perf(render): optimize tile caching`

*   **`test`**: Adding missing tests or correcting existing tests.
    *   *Use when:* Adding unit tests, fixing flaky tests, or improving coverage.
    *   *Example:* `test: add coverage for mask service`

*   **`build`**: Changes that affect the build system or external dependencies.
    *   *Use when:* Updating `pyproject.toml`, `setup.py`, or dependencies.
    *   *Example:* `build: update optional runtime dependency`

*   **`ci`**: Changes to our CI configuration files and scripts.
    *   *Use when:* Modifying GitHub Actions workflows or hooks.
    *   *Example:* `ci: fix release workflow trigger`

*   **`chore`**: Other changes that don't modify src or test files.
    *   *Use when:* Updating `.gitignore`, license files, or maintenance scripts.
    *   *Example:* `chore: update gitignore`

*   **`revert`**: Reverts a previous commit.
    *   *Use when:* Undoing a commit that caused issues.
    *   *Example:* `revert: feat(sam): add auto-segmentation support`

#### 2. Scope (Required)

A noun describing the section of the codebase surrounded by parenthesis, e.g., `(catalog)`, `(sam)`, `(rendering)`. While the automated hook permits optional scopes, we require them for all contributions to keep the changelog organized.

#### 3. Breaking Change

If your change breaks backward compatibility, you **must** append `!` after the type/scope (e.g., `feat(api)!:`). This signals a **Breaking Change** and will trigger a Major version bump.

#### 4. Subject

A concise description of the change in the imperative mood (e.g., "change" not "changed" or "changes").

### How It Affects Versioning

| Commit Type | Example | Version Bump |
| :--- | :--- | :--- |
| `fix` | `fix(ui): resolve flicker on resize` | **Patch** (0.0.x) |
| `feat` | `feat(sam): add auto-segmentation` | **Minor** (0.x.0) |
| `perf` | `perf(render): optimize tile caching` | **Patch** (0.0.x) |
| `!` (Breaking) | `feat(api)!: remove deprecated method` | **Major** (x.0.0) |
| `docs`, `chore`, etc. | `docs: update readme` | **None** |

**Note:** Do not manually update version numbers in files. The CI pipeline handles this automatically based on your commit history.

## Review Process

Passing the automated tools is just the baseline. The maintainers review Pull Requests to ensure the codebase remains healthy, maintainable, and consistent. We look beyond the syntax to the intent of your changes.

### What We Look For

*   **Architectural Integrity**: Does the change respect the boundaries defined in the [Architecture](#architecture--separation-of-concerns) section? Does it leak implementation details into the public API?
*   **Design Intent**: Is the solution robust? Does it solve the problem at the right layer (e.g., in `core` vs `ui`)?
*   **Code Quality**: Is the code expressive and readable? Do variable names match our [Naming Conventions](#naming-conventions)?
*   **Documentation Fidelity**: Are the docstrings actually helpful to a human reader, or are they just satisfying the linter? Do they capture *why* a complex decision was made?
*   **Test Quality**: Do the tests cover edge cases? Are they testing behavior rather than implementation details?

