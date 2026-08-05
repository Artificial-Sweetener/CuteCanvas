# Ferrastra development boundary

Ferrastra is built as a Cargo workspace and packaged with PyO3 and maturin. The
Python package treats `ferrastra._native` as private; callers use only the typed
`ferrastra` facade.

The active crate inventory and every future dependency edge are defined in the
repository architecture policy. A crate is created only when executable code
for that owner begins. This keeps Stage 0 enforceable without empty framework
scaffolding.

The complete architecture, operation-entry checklist, conformance categories,
waiver policy, and migration phases are documented in the repository
`ARCHITECTURE.md` and `FERRASTRA_DESIGN.md`.

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
.venv\Scripts\python tools\check_ferrastra_architecture.py
.venv\Scripts\python tools\check_ferrastra_operations.py
.venv\Scripts\python tools\check_ferrastra_ownership.py
.venv\Scripts\python tools\check_ferrastra_benchmarks.py
.venv\Scripts\python -m ruff check --config ruff-ferrastra.toml .
.venv\Scripts\python -m pyright -p pyright-ferrastraconfig.json
.venv\Scripts\python tools\verify_ferrastra_wheel.py
```

## Supported native platforms

Every Ferrastra release builds and verifies native artifacts for these minimum
targets:

- Windows x64: `x86_64-pc-windows-msvc`
- Linux x64: `x86_64-unknown-linux-gnu`
- Apple Silicon macOS: `aarch64-apple-darwin`

The CPython 3.10 stable ABI supports the declared Python 3.10 through 3.14
range. CI exercises every supported Python minor on Linux x64 and verifies the
same native wheel boundary on Windows x64 and Apple Silicon.
