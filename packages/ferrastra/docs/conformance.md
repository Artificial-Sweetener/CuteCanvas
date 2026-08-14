# Conformance and benchmark policy

Ferrastra operations are admitted only with a stable semantic identity, explicit
exposure class, complete computation and authoring descriptor, typed parameters
and units, input and output products, backward demand, forward damage,
coordinate, numerical and quality behavior, request-aware capability and cost
analysis, structured diagnostics, bounded memory, cancellation semantics,
cross-frontend construction when public, and a reference result.
`benchmarks/ferrastra_manifest.toml` defines the required measurement environment,
input classes, percentiles, memory observations, thread counts, and deterministic
seeds. Its controlled operation case also fixes the source and destination
dimensions, edge and working-space modes, total and scratch budgets, and the
operation-specific acceptance limits used by the executable benchmark gate.

The identity operation establishes the baseline spatial contract: exact regional
demand and damage, byte-identical output across valid strides, deterministic
product identity, bounded memory, and cancellation without partial publication.
Operations with material numerical or performance behavior add a benchmark
entry declaring canonical and adversarial inputs, latency thresholds for
p50/p95/p99, throughput, peak and allocated memory ceilings, cancellation
latency, and supported quality modes. Measurements repeat at each declared
thread count to expose nondeterministic scheduling or hidden global execution.

Lanczos3 adds an independent direct two-dimensional numerical oracle,
scale-aware minification cases, all declared edge modes, encoded and linear
working-space checks, premultiplied transparency, varied source and destination
strides, empty and one-pixel products, cancellation and scratch rejection, and
byte-exact tile-seam equivalence. Its optimized CPU path uses bounded reusable
row scratch and an operation-local coefficient cache.

Sampled-view Lanczos3 proves phase-stable non-power-of-two grids and regional
equivalence. Raster affine operations have independent nearest and bilinear
coordinate oracles, transparent-edge cases, premultiplied range checks, and
tile-versus-monolithic equality. Coverage affine has independent scalar linear
and area oracles, nearest selection, transparent and clamped edges,
range-preservation, and partition equivalence. Every adapter subscribes native
cancellation and publishes only a complete admitted result.

Run the policy gate with:

```powershell
.venv\Scripts\python tools\check_ferrastra_benchmarks.py
```

Run the controlled measurement lane against an optimized native build with:

```powershell
Push-Location packages\ferrastra
..\..\.venv\Scripts\python -m maturin develop --release
Pop-Location
.venv\Scripts\python tools\ferrastra_benchmarks.py
```
