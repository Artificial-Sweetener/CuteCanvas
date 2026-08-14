<h1 align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Artificial-Sweetener/CuteCanvas/main/assets/logos/ferrastra-logo-on-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/Artificial-Sweetener/CuteCanvas/main/assets/logos/ferrastra-logo-on-light.svg">
    <img alt="Ferrastra — oxidized image processing" src="https://raw.githubusercontent.com/Artificial-Sweetener/CuteCanvas/main/assets/logos/ferrastra-logo-on-light.svg" width="720">
  </picture>
</h1>

<p align="center">
  <a href="https://github.com/Artificial-Sweetener/CuteCanvas/blob/main/FERRASTRA_DESIGN.md"><img src="https://img.shields.io/badge/phase-3-16a34a" alt="Phase 3"></a>
  <a href="https://github.com/Artificial-Sweetener/CuteCanvas/actions/workflows/release.yml"><img src="https://img.shields.io/github/actions/workflow/status/Artificial-Sweetener/CuteCanvas/release.yml?branch=main&amp;label=Tests" alt="Test status"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python 3.10+"></a>
  <a href="https://www.rust-lang.org/"><img src="https://img.shields.io/badge/rust-1.93.1-000000?logo=rust&amp;logoColor=white" alt="Rust 1.93.1"></a>
  <a href="https://github.com/Artificial-Sweetener/CuteCanvas/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-GPL--3.0--or--later-blue" alt="GPL-3.0-or-later license"></a>
</p>

Ferrastra is an independently buildable CPU-first, typed, spatial graphics
product engine. Its immutable graph, canonical serialization, native raster
source, regional demand and damage, bounded runtime, and deterministic product
identity are available from Rust and Python. Canonical whole-image and
sampled-view Lanczos3, affine raster, and Coverage8 affine operations provide
stable tiled and monolithic results without introducing presentation concepts.

Install a local development build from the repository root with:

```powershell
.venv\Scripts\python -m pip install -e packages\ferrastra
```

The wheel uses the CPython 3.10 stable ABI and supports Python 3.10 through
3.14 from one wheel per supported native platform. The minimum platform set is
Windows x64, Linux x64, and Apple Silicon macOS. Ferrastra does not install or
import Qt, QPane, or CuteCanvas.

```python
from ferrastra import Engine, EvaluationBudget, GraphBuilder, Region

engine = Engine()
source_pixel = bytes((12, 24, 36, 255))
revision = engine.add_rgba8(source_pixel * 4, 2, 2)

builder = GraphBuilder(1)
builder.add_node(1, "ferrastra.source.raster")
builder.set_source_revision(1, revision)
builder.add_node(2, "ferrastra.resample.lanczos3")
builder.connect(1, "result", 2, "source")
builder.set_integer(2, "source_width", 2)
builder.set_integer(2, "source_height", 2)
builder.set_integer(2, "destination_width", 5)
builder.set_integer(2, "destination_height", 3)
builder.add_output("result", 2)

compiled = engine.compile(builder.build())
region = Region(0, 0, 5, 3)
requirements = engine.requirements(compiled, "result", region)
result = engine.evaluate(
    compiled,
    "result",
    region,
    EvaluationBudget(
        memory_bytes=requirements.memory_bytes,
        scratch_bytes=requirements.scratch_bytes,
    ),
)
assert result.pixels == source_pixel * 15
```

See the [Ferrastra design charter](https://github.com/Artificial-Sweetener/CuteCanvas/blob/main/FERRASTRA_DESIGN.md)
and [package source](https://github.com/Artificial-Sweetener/CuteCanvas/tree/main/packages/ferrastra)
for its product boundary and implementation contract.
