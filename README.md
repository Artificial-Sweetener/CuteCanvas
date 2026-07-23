# QPane + CuteCanvas

This monorepo contains two independently published PySide6 packages with one
deliberate dependency direction:

```text
CuteCanvas -> QPane
QPane      x  CuteCanvas
```

## QPane

QPane is the high-performance viewer and raster/vector rendering SDK. It owns
the viewport, affine scene projection, clipping, hit testing, compositing,
pyramids, tiles, refinement, cache coordination, and semantic vector sampling.
Large images, sparse live sources, and reusable vector documents all pass
through the same immutable `RenderScene` pipeline.

```powershell
pip install qpane
python examples\qpane_demo.py
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
python examples\cutecanvas_demo.py
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
- `examples/qpane_demo.py`: the single polished QPane example.
- `examples/cutecanvas_demo.py`: the single polished CuteCanvas example.
- `tests/`: renderer, editor, integration, abuse, performance, and packaging
  proof shared by the monorepo.

Both packages are licensed under GPL-3.0-or-later.

## Development and releases

Install `requirements-dev.txt` into the repository virtual environment to use
both editable packages and the shared verification tools. QPane and CuteCanvas
build from their own `pyproject.toml`, produce independent wheels, and publish
only from product-specific tags: `qpane-vX.Y.Z` and `cutecanvas-vX.Y.Z`.
