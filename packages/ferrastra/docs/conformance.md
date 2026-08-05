# Conformance and benchmark policy

Ferrastra operations are admitted only with a stable semantic identity, explicit
input and output products, backward demand, forward damage, numerical and
quality behavior, bounded memory, cancellation semantics, and a reference
result. `benchmarks/ferrastra_manifest.toml` defines the required measurement
environment, input classes, percentiles, memory observations, thread counts,
and deterministic seeds.

Stage 0 contains no graphics operation and no benchmark registration. Before
operation code is added, its benchmark entry must declare reference and
adversarial inputs, latency thresholds for p50/p95/p99, throughput, peak and
allocated memory ceilings, cancellation latency, and the supported quality
modes. Results are compared on the manifest's reference system and repeated at
each declared thread count to expose nondeterministic scheduling or hidden
global execution.

Run the policy gate with:

```powershell
.venv\Scripts\python tools\check_ferrastra_benchmarks.py
```
