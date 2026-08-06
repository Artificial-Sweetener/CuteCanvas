# Ferrastra Python Package Guidance

The root `AGENTS.md`, `FERRASTRA_DESIGN.md`, `RCANDY_DESIGN.md`, and
`ARCHITECTURE.md` apply. This file defines the Ferrastra Python package's local
ownership and proof requirements. Rust source follows `crates/AGENTS.md`.

## Product identity

Ferrastra is a CPU-first, framework-neutral, document-neutral native graphics
product engine. It evaluates typed immutable products through spatially planned
graphs and owns transactional native source editing. It does not own authoring
models, tools, undo, viewport policy, GUI adaptation, or presentation.

## Python boundary

The Python package owns typed public contracts, stable exception translation,
operation schemas, opaque native handles, lifecycle control, and adaptation of
the private native extension. When implemented, `ferrastra.rcandy` owns the typed
Python language surface and coordinated authored-artifact contracts while the
native language crate owns parsing and lowering. Python modules do not own
numerical kernels, graph semantics, planning, scheduling, caches, native
storage, or host policy.

`src/ferrastra/ferrastra.pyi` is the authoritative public contract. Keep runtime
exports, annotations, and native signatures consistent with it. Public values
use precise product and handle types rather than untyped dictionaries, capsules,
or incidental native representations.

Validate shape, format, stride, bounds, mutability, contiguity, alignment,
lifetime, cancellation, and budget assumptions at the boundary that receives
them. Translate native failures into stable domain exceptions without losing
their cause. Do not retain borrowed buffers beyond their documented call or
lease lifetime.

Keep the Python layer thin, deterministic, and free of hidden global execution
or cache state. A dependency addition must be necessary for the public boundary
and must preserve independent wheel installation.

## Integration surface

Organize the public package around typed product construction, graph evaluation,
source editing, cancellation, and diagnostics workflows rather than native crate
structure. Give common workflows one obvious entry path with focused builders,
requests, products, and session handles for advanced control. Callers do not
assemble registries, runtimes, stores, caches, or native binding objects.

Do not force the package into one facade class. A cohesive module or assembly
object with focused typed handles is valid when it preserves ownership. Do not
make unrelated one-off filter functions, untyped dictionaries, or private native
objects the primary integration API.

## Stage 0

Stage 0 exposes package identity so native wheel building, installation, typing,
and architecture enforcement are executable. It contains no graphics kernel,
parser, language crate, placeholder engine API, mock public operation, or
speculative product contract. Non-production schemas and fixtures may verify the
planned R-Candy constraints without creating public behavior. Add product,
graph, runtime, store, raster, vector, painting, or language contracts only in
the phase and owner authorized by the design charters.

## Public surface

Public changes update the stub, runtime exports, native boundary, documentation,
and `packages/ferrastra/examples/ferrastra_demo.py` together. Verify strict typing, package-boundary
tests, native version agreement, architecture and ownership checks, and an
isolated built-wheel import with only declared dependencies.

Published wheels support Windows x64, Linux x64, and Apple Silicon macOS. A
boundary or packaging change is complete only after every target's build and
isolated-install checks pass.

## Test organization and proof

Organize Ferrastra Python tests by the behavior owners for public contracts,
typed values and schemas, graph construction and serialization, source and
product handles, edit sessions, cancellation and budgets, diagnostics and
exceptions, buffer and FFI validation, R-Candy authored artifacts, native-version
agreement, and wheel packaging.

`packages/ferrastra/TEST_POLICY.toml` maps the Python package and every Ferrastra
crate production area to required Python, Rust, cross-language, conformance,
fuzz, benchmark, and packaging proof. Changes to the public contract, native
boundary, graph or value schema, serialization, exception mapping, ownership,
or packaging update that map in the same work.

Public-contract tests use the supported Python surface rather than the private
extension. Boundary tests cover invalid shapes, formats, strides, bounds,
mutability, alignment, lifetimes, cancellation, budgets, and native failures and
prove stable exception translation without interpreter crashes or leaked partial
state. Handle tests prove ownership, borrowing, release, cancellation, teardown,
and use-after-close behavior.

Cross-language fixtures prove that Python and Rust construct, normalize,
serialize, diagnose, and patch equivalent graphs. R-Candy fixtures additionally
prove coordinated source artifacts, source maps, locked resolution, structured
diagnostics, and graph identity. Packaging proof builds the wheel and exercises
the supported facade from an isolated environment containing only declared
dependencies.
