# Ferrastra + QPane + CuteCanvas

This monorepo contains three independently published graphics packages with
enforced dependency directions:

```text
CuteCanvas -> QPane
CuteCanvas -> Ferrastra
QPane      -> Ferrastra
```

## Ferrastra

Ferrastra is the CPU-first, Qt-neutral native graphics product engine described by
[`FERRASTRA_DESIGN.md`](FERRASTRA_DESIGN.md). Its Stage 0 package establishes the
Rust/PyO3/Python boundary, ownership policy, architecture gates, and
conformance infrastructure without adding production graphics behavior.

[`RCANDY_DESIGN.md`](RCANDY_DESIGN.md) defines R-Candy, Ferrastra's typed
declarative graph-authoring language and structured authoring surface. Stage 0
establishes its architecture without adding language behavior or an empty crate.

See [the Ferrastra package guide](packages/ferrastra/README.md) and
[`ARCHITECTURE.md`](ARCHITECTURE.md).

```powershell
python packages\ferrastra\examples\ferrastra_demo.py
```

## QPane

QPane is the high-performance viewer and raster/vector rendering SDK. It owns
the viewport, affine scene projection, clipping, hit testing, compositing,
pyramids, tiles, refinement, cache coordination, and semantic vector sampling.
Large images, sparse live sources, and reusable vector documents all pass
through the same immutable `RenderScene` pipeline.

```powershell
pip install qpane
python packages\qpane\examples\qpane_demo.py
```

```python
from PySide6.QtGui import QImage
from qpane import QPane

viewer = QPane()
viewer.setImage(QImage("large-image.tif"))
```

See [the QPane package guide](packages/qpane/README.md) for the declarative
scene, raster-provider, and semantic-vector SDK.

## CuteCanvas

CuteCanvas is the layered editor built on QPane. It owns compositions, generic
editable layers, selections, history, raster and mask painting, placed assets,
vector authoring, move/free-transform workflows, persistence, and optional SAM
integration. Editor work can improve QPane whenever profiling identifies a
source-neutral renderer, viewport, cache, or SDK owner.

```powershell
pip install cutecanvas
python packages\cutecanvas\examples\cutecanvas_demo.py
```

```python
from cutecanvas import CuteCanvas

canvas = CuteCanvas(features=("mask",))
```

The [CuteCanvas package guide](packages/cutecanvas/README.md) introduces the
editor, while [the editor documentation](packages/cutecanvas/docs/getting-started.md)
covers its public facade and workflows.

## Repository layout

- `packages/qpane/`: QPane metadata, source, contract, tests, and documentation.
- `packages/cutecanvas/`: CuteCanvas metadata, source, contract, tests, and documentation.
- `packages/ferrastra/`: Ferrastra metadata, typed facade, tests, and documentation.
- `crates/`: executable Ferrastra native crates.
- `RCANDY_DESIGN.md`: normative R-Candy language and structured-authoring charter.
- `packages/ferrastra/examples/ferrastra_demo.py`: the single public Ferrastra example.
- `packages/qpane/examples/qpane_demo.py`: the single polished QPane example.
- `packages/cutecanvas/examples/cutecanvas_demo.py`: the single polished CuteCanvas example.
- `tools/testing/`: policy aggregation, ownership-driven test selection, and
  repository-tool contract tests.

Each product owns its tests and `TEST_POLICY.toml`. Tests are organized by
behavioral area and proof kind so focused work does not require private pytest
node IDs or a complete monorepo run.

All three packages are licensed under GPL-3.0-or-later.

## Development and releases

Install `requirements-dev.txt` into the repository virtual environment to use
all editable packages and the shared verification tools. Each product builds
an independent wheel and publishes only from its product tag:
`ferrastra-vX.Y.Z`, `qpane-vX.Y.Z`, or `cutecanvas-vX.Y.Z`.
