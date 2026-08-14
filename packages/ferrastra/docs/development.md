# Ferrastra development boundary

Ferrastra is built as a Cargo workspace and packaged with PyO3 and maturin. The
Python package treats `ferrastra._native` as private; callers use only the typed
`ferrastra` facade.

The active crate inventory and every dependency edge are defined in the
repository architecture policy. Each crate has one executable owner: core
contracts, graphs, stores, runtime orchestration, raster operations, engine
assembly, or Python boundary adaptation.

The complete architecture, operation-entry checklist, conformance categories,
waiver policy, and migration phases are documented in the repository
`ARCHITECTURE.md`, `FERRASTRA_DESIGN.md`, and `RCANDY_DESIGN.md`.

The repository bootstrap installs the pinned Rust 1.93.1 toolchain components,
`cargo-deny` 0.20.2, maturin, Ruff, Pyright, and the editable package. Run the
native gates directly with:

```powershell
cargo fmt --all --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace --all-features
cargo deny check
```

Run the cross-language policy, strict Python, and packaging gates with:

```powershell
.venv\Scripts\python tools\check_architecture.py
.venv\Scripts\python tools\check_ferrastra_operations.py
.venv\Scripts\python tools\check_ferrastra_ownership.py
.venv\Scripts\python tools\check_ferrastra_benchmarks.py
.venv\Scripts\python -m ruff check --config ruff-ferrastra.toml .
.venv\Scripts\python -m pyright -p pyright-ferrastraconfig.json
.venv\Scripts\python tools\verify_ferrastra_wheel.py
```

Measure the checked-in Lanczos3 latency, memory, cancellation, and deterministic
thread-budget contract against an optimized native build with:

```powershell
Push-Location packages\ferrastra
..\..\.venv\Scripts\python -m maturin develop --release
Pop-Location
.venv\Scripts\python tools\ferrastra_benchmarks.py
```

The executable case and all acceptance limits come from
`benchmarks/ferrastra_manifest.toml`.

## Supported native platforms

Every Ferrastra release builds and verifies native artifacts for these minimum
targets:

- Windows x64: `x86_64-pc-windows-msvc`
- Linux x64: `x86_64-unknown-linux-gnu`
- Apple Silicon macOS: `aarch64-apple-darwin`

The CPython 3.10 stable ABI supports the declared Python 3.10 through 3.14
range. CI exercises every supported Python minor on Linux x64 and verifies the
same native wheel boundary on Windows x64 and Apple Silicon.
