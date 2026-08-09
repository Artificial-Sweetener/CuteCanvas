# CuteCanvas Package Guidance

The root `AGENTS.md` applies. This file defines CuteCanvas's local ownership and
proof requirements.

## Product identity

CuteCanvas is a performant embeddable raster/vector document editor. Its public
facade makes document, layer, and tool workflows coherent without concentrating
behavior in one widget or service graph.

## Ownership

CuteCanvas owns:

- independent document identity, canvas, metadata, persistence, and export;
- ordered editable layer instances, resource identity, sharing, and lifetimes;
- host capability policy, durable user locks, and one operation resolver;
- unified chronological undo/redo and atomic edit transactions;
- editable raster and coverage storage, masks, selections, and painting;
- placed- and smart-asset provenance, conversion, rasterization, and publication
  workflows;
- vector revision authoring around immutable semantic vector values;
- authored-effect resources, source/graph persistence, model interaction,
  package trust and resolution, generated controls, preview admission,
  diagnostics, and undoable effect revisions;
- layer and pixel movement, floating edits, free transforms, authoring tools,
  options, overlays, and transient feedback; and
- autosave, failure recovery, and SAM integration.

## Internal ownership boundaries

Tools translate input into commands and UI objects present state. Neither owns
durable document, selection, geometry, pixel, history, permission, or rendering
state. Every durable edit uses the document's single history. Host policy and
user locks remain separate inputs to the one operation resolver.

`SnapConfiguration` owns durable policy, guides, and grid settings.
`SnapCandidateProvider` captures stationary scene targets once per gesture.
Movement and geometric authoring use separate session resolvers.
`SnapGuideFeedback` owns transient guide presentation. `SnappingSubsystem`
constructs these collaborators at the editor lifecycle boundary. Shape and path
tools own their gesture lifecycle and delegate coordinates through their
authoring port; freehand tools, painting, fills, and intelligent selection do
not receive that port.

Retained pixel-selection and mask shapes delegate canvas clipping and preview
projection to `CoverageCanvasAperture`. `ActiveMaskCanvasAperture` owns
mask-specific aperture geometry. Tools do not reproduce either concern.

`SceneLayerSelectionController` owns an ordered selection with the active member
last. `SceneLayerMoveController` owns translation-only layer-set sessions.
`SceneLayerTransformController` owns single-layer affine transforms.
`SceneLayerMappingPreview` presents affine, projective, piecewise, or bilinear
workflows as one coherent transient set. `LayerMappingMutationOwner` commits exact mapping sets
through one layer-store publication and one history edit.

Axis snapping retains its optimized scalar path. Oriented snapping uses exact
finite manipulation edges, a frozen spatial index, deterministic ranking, and
device-pixel thresholds. Shared-edge resize infers one current seam between
exactly two eligible layers. Midpoint drags derive both affine previews from one
scalar. A common-corner endpoint pivots only along the continuous rail shared by
both participants and derives paired piecewise previews from immutable bases.
Both operations commit or cancel atomically. Alpha contours never define the
seam, and interaction never resamples or bakes layer pixels.

## Facade and public surface

The editor facade is the obvious starting point for integration. Common document,
layer, and tool workflows require no construction of internal controllers or
knowledge of storage, rendering, history, or scheduling internals. Expose typed
document and layer handles with focused document, layer, tool, selection,
history, and export subfacades. Avoid routine raw identifier pairs, private
collaborator access, service locators, and a god widget. Programmer errors fail
clearly; unavailable operations return stable reasons and available alternatives.

`src/cutecanvas/cutecanvas.pyi` is CuteCanvas's authoritative typed contract.
Public changes update it, the implementation, CuteCanvas documentation, and
`packages/cutecanvas/examples/cutecanvas_demo.py` together. The demo is a coherent layered editor
with an intentional canvas, tools and options, layer tree, selections,
transforms, painting, masks, raster/vector/placed layers, undo/redo, and
persistence rather than a collection of test panels.

## Test organization and proof

Organize CuteCanvas tests by the behavior owners for facade and public contracts,
documents and resources, history and transactions, layers and groups, selections
and masks, raster and vector authoring, painting, movement and transforms, tools
and policy, authored effects, persistence and recovery, mounted editor workflows,
and packaging.

`packages/cutecanvas/TEST_POLICY.toml` maps every CuteCanvas production area and
public boundary to its required test areas. Changes to durable state, mutation,
history, policy, authoring, persistence, recovery, facade, or workflow contracts
update that map in the same work.

Every durable mutation proves success, rejection atomicity, chronological undo,
redo, and restored observable state. Persistence proof covers canonical round
trips, unavailable resources, interrupted writes, recovery, and preservation of
valid prior state. Authored-effect proof covers source and graph coordination,
package and capability admission, generated controls, diagnostics, preview,
transactional patches, undo, and retention of unavailable operations.

Mounted workflow proof uses real editor widgets for input routing, tool
lifecycle, overlays, repaint, focus, publication, and teardown. Abuse proof
covers rapid document switching, edit/undo chains, input storms, stale work,
source removal, cache pressure, large and sparse content, persistence failure,
and redraw equality. Performance proof covers interactive latency, bounded
memory, invalidation scope, painting, transforms, history, and large-document
workflows. Packaging proof installs the product with only declared dependencies
and exercises its supported facade.
