<p align="center">
  <img src="../../assets/logos/logo-black.png#gh-light-mode-only" alt="QPane" width="320">
  <img src="../../assets/logos/logo-white.png#gh-dark-mode-only" alt="QPane" width="320">
</p>

[![License: GPL-3.0-or-later](https://img.shields.io/badge/License-GPL--3.0--or--later-blue.svg)](../../LICENSE) [![semantic-release](https://img.shields.io/badge/semantic--release-angular-e10079?logo=semantic-release)](https://github.com/semantic-release/semantic-release) [![PyPI](https://img.shields.io/pypi/v/qpane.svg)](https://pypi.org/project/qpane/) [![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/) [![PySide6](https://img.shields.io/badge/PySide6-6.7.3%2B-41CD52?logo=qt&logoColor=white)](https://pyside.org)

**QPane** is a high-performance, **open-source (GPLv3 or later)** image viewer and raster/vector rendering SDK for PySide6.

It bridges the gap between a raw `QGraphicsView` and a full rendering engine, providing a drop-in widget for **interactive workflows** involving high-resolution image inspection, dataset curation, scene review, comparison, and custom visualization.

Whether you are building a simple photo viewer or a mission-critical imaging system, QPane adapts to your resource constraints.

## Highlights
*   **Drop-in PySide6 Widget:** A production-ready image viewer you can add to any layout in a few lines of code.
*   **True FOSS:** Distributed under GPLv3 or later to ensure it remains free for everyone. No pro versions, no hidden costs.
*   **CPU-First Performance:** Renders massive images smoothly using system RAM, ensuring responsiveness on any hardware—from laptops to workstations.
*   **Fluid Pan & Zoom Navigation:** Silky smooth zooming, panning, and tiling out of the box.
*   **Declarative Render Scenes:** Arrange shared raster and vector sources into review grids, contact sheets, overlays, and layered views without flattening pixels.
*   **Public Rendering SDK:** Build custom sources, scene layers, effects, hit tests, and viewer tools while QPane owns tiling, damage, caching, and scheduling.
*   **Inspection and Layout SDK:** Link native-size views by normalized region,
    arrange stable responsive target grids, and compare independent targets
    without merging their coordinate spaces.
*   **Host MIME Dragging:** Materialize files, companion variants, text, or
    custom MIME data through one cancellable native drag lifecycle.
*   **Focused Runtime:** Qt and ordinary CPU-side imaging libraries provide the complete viewer and rendering SDK.
*   **Native High-DPI Support:** Automatically adapts to different monitor pixel densities and OS zoom levels for crisp rendering anywhere.

<p align="center">
  <img src="../../assets/videos/zoom.gif" alt="QPane zoom demo" width="852" height="480">
</p>
<blockquote>
  <p>Deep-zoom navigation on a high-resolution Hubble composite. Note the cursor-anchored zooming and fluid responsiveness even at extreme magnification.</p>
  <p><strong>Credit:</strong> <em>"Hubble's Spectacular Wide View of the Universe"</em> (NASA, ESA, G. Illingworth and D. Magee (University of California, Santa Cruz), K. Whitaker (University of Connecticut), R. Bouwens (Leiden University), P. Oesch (University of Geneva), and the Hubble Legacy Field team).</p>
  <p><strong>Source:</strong> <a href="https://esahubble.org/images/heic1909a/">ESA/Hubble Original</a></p>
</blockquote>

## Installation

QPane includes the complete viewer, raster/vector renderer, and extension SDK.

```bash
# Viewer and rendering SDK
pip install qpane
```

## The Gap in the Qt Ecosystem

If you are building a Python GUI that needs to display images, you typically face a dilemma between two built-in widgets, neither of which is quite right for the job:

### 1. The `QLabel` Trap
It's easy to use (`setPixmap`), but it's static. You get no zooming, no panning, and no coordinate system. It's a picture frame, not a tool.

### 2. The `QGraphicsView` Reality
`QGraphicsView` is the standard recommendation for custom viewports, but it is a low-level building block, not a complete solution. It provides a scene graph, but it doesn't give you a modern image viewing experience out of the box.

To build a production-grade viewer with `QGraphicsView`, you inevitably end up writing the same complex infrastructure:
*   **Interaction Logic:** Implementing anchored zooming and smooth panning.
*   **Coordinate Systems:** Mapping mouse events from the view to the scene to the image pixels for precise tool handling.
*   **Performance Tuning:** Managing execution, caching, and tiling to keep the UI responsive when the image gets large.

**QPane is that infrastructure.** It encapsulates the hundreds of hours of specialized engineering required to turn a raw Qt widget into a professional image viewer.

## The Engine: CPU-First & Raster-Optimized

QPane rejects the modern "GPU-brute-force" approach in favor of deterministic, CPU-friendly optimizations reminiscent of high-performance 2D engines from the 90s.

I originally built QPane for my **Stable Diffusion frontend**, where the GPU is already at 100% load running inference. I needed a viewer that wouldn't fight the AI model for VRAM. This architecture makes QPane ideal for **any resource-constrained environment**, from scientific imaging on office laptops to embedded systems with limited graphics acceleration.

### 1. The Raster Pipeline
QPane avoids Qt's item-heavy scene graph and uses its own raster-first scene model, closer to a map engine than a traditional canvas. Instead of rendering the image, QPane renders the *viewport*.
*   **Software Tiling:** Large images are sliced into small CPU-resident tiles. Instead of thousands of `QGraphicsItem` objects, QPane resolves lightweight scene layers into visible tile work using raw coordinate math.
*   **Viewport Culling:** Only the pixels currently visible on screen are processed. You can load a 5GB satellite scan, and QPane will only render the 1920x1080 pixels needed for your monitor.
*   **Background Pyramids:** The execution runtime generates downsampled versions of your image away from the GUI thread. When you zoom out, QPane instantly swaps to a lower-resolution tier without stuttering over a 100MB image.
*   **Bit-Blit Scrolling:** When you pan, QPane doesn't redraw the screen. It shifts the existing pixel buffer and only renders the newly exposed "damage strips" at the edges. This keeps scrolling silky smooth even at high resolutions.

### 2. Smart Memory Management
QPane counts every byte of every tile. By default, it dynamically adjusts its cache based on system memory pressure, but can be locked to a strict budget for deterministic performance.

*   **Auto Mode (Consumer Friendly):** Uses `psutil` to monitor available RAM. "Use what's free, but leave 10% headroom for the OS." Ideal for general-purpose viewers or apps running alongside other heavy software.
*   **Hard Mode (Dedicated Resources):** Locks QPane to a specific memory budget (e.g., 4GB). "Take 4GB of RAM and keep as many tiles in memory as possible." Ideal for dedicated imaging systems or kiosk applications where the viewer is the primary task.

```python
# Configure for a dedicated system with 4GB cache
conf = Config().configure(
    cache={"mode": "hard", "budget_mb": 4096},
)
```

## Key Features

### 1. Advanced Viewing Capabilities
*   **Immutable Render Scenes:** Build contact sheets, two-up layouts, overlays, and custom review grids from shared raster and vector sources. Every layer participates in the same pyramid, tile, clipping, and damage pipeline.
*   **Raster, Vector, and Hybrid Sources:** Combine tiled images, semantic vector documents, and hybrid vector/raster presentations without building a second renderer.
*   **Linked Views:** Perfect for "Before/After" workflows. Group multiple images into a **Linked Group**, and panning/zooming one image synchronizes the view state across the entire group.
*   **Catalog System:** QPane manages source image identity for you. Add images with `addImage()`, select them by stable UUID, and use `catalog()` when your host needs ordered navigation state.
*   **High-DPI Ready:** QPane detects the pixel density of the monitor it's on and renders at the native resolution. Drag the window between monitors with different OS zoom levels, and QPane instantly rebuilds its render buffers to match the new pixel density without stuttering.

### 2. The Rendering SDK
QPane is also the rendering foundation for applications that need more than a
single image. A `RenderScene` is an immutable description of what to draw;
`RenderLayer` instances place reusable sources without copying their pixels.

*   **Shared source identity:** Reuse one `RasterSource` or `VectorSource` in multiple scenes and transformed layer instances while sharing cached render products.
*   **Source-neutral rendering:** Raster, vector, and hybrid content use the same visibility, damage, refinement, cache, and scheduling machinery.
*   **Presentation effects:** Add host-owned highlights and outlines without modifying source pixels or inventing editor state in the renderer.
*   **Extension primitives:** Register viewport and scene overlays, diagnostics providers, and viewer tools through the supported facade.

## Developer Experience

QPane is designed to be the library I wish I had. It uses a **Facade Pattern** to hide complexity: you work with catalog images, immutable scenes, tools, and signals, while QPane handles tile managers, pyramids, damage, and bounded execution internally.

*   **Native Qt Feel:** It's a `QWidget`. Add it to a layout, connect signals such as `catalogSelectionChanged` and `sceneChanged`, and it just works.
*   **Snapshot-Style Config:** No global state spaghetti. Create a `Config` object, set your preferences (cache size, keybindings), and pass it in; QPane keeps its own copy for the widget.
*   **Diagnostics HUD:** Easy to wire into your app. Bind your preferred shortcut to toggle the overlay and see memory usage, render times, and execution queues.
*   **Typed Public SDK:** The facade exposes the complete supported viewer and rendering vocabulary without requiring private-module imports.

<p align="center">
  <img src="../../assets/videos/diagnostics.gif" alt="QPane diagnostics overlay demo" width="852" height="480">
</p>
<blockquote>
  <p>Real-time performance monitoring. The diagnostics overlay visualizes memory usage, render latency, and the active tile grid to help debug resource constraints.</p>
  <p><strong>Credit:</strong> <em>"Woman Holding a Balance"</em> by Johannes Vermeer, courtesy National Gallery of Art.</p>
  <p><strong>Source:</strong> <a href="https://www.nga.gov/artworks/1236-woman-holding-balance">National Gallery of Art</a></p>
</blockquote>

## Try the Demo

The source repository includes a comprehensive QPane demo that teaches the viewer and rendering SDK while letting you test large-image navigation, comparison, diagnostics, scenes, and extensions without writing any code. Clone the repository to run it; examples are intentionally excluded from the PyPI wheel.

```bash
# From the repository root
python examples/qpane_demo.py
```

## Usage

```python
from PySide6.QtGui import QImage
from qpane import QPane

# 1. Initialize the polished viewer.
viewer = QPane()

# 2. Load Data
first = viewer.addImage(QImage("scan_001.tif"), label="First scan")
viewer.addImage(QImage("scan_002.tif"), label="Second scan")
viewer.selectCatalogImage(first.entry_id)

# 3. Connect Signals
viewer.catalogSelectionChanged.connect(
    lambda entry: print(f"Now viewing {entry.label if entry else 'nothing'}")
)
viewer.sceneChanged.connect(
    lambda scene: print(f"Scene changed: {scene is not None}")
)
```

## Documentation

*   **[Getting Started](docs/getting-started.md):** A step-by-step guide to your first integration.
*   **[Configuration](docs/configuration.md):** Learn how to tune the cache, execution policy, and interaction behavior.
*   **[Configuration Reference](docs/configuration-reference.md):** The complete list of every field and default value.
*   **[Catalog and Navigation](docs/catalog-and-navigation.md):** Managing image lists and linked views.
*   **[Rendering SDK](docs/rendering-sdk.md):** Building layered raster/vector scenes, custom sources, hit tests, and effects.
*   **[Advanced Renderer Integration](docs/integration-sdk.md):** Participating directly in QPane's scene, cache, scheduling, diagnostics, and renderer lifecycle.
*   **[Viewer Workflows](docs/viewer-workflows.md):** Comparison, placeholders, clipboard operations, and host integration.
*   **[Host Cookbook](docs/host-cookbook.md):** Connect the complete viewer, catalog, tool, diagnostics, and rendering surface in one application.
*   **[Interaction Modes](docs/interaction-modes.md):** Switching between pan/zoom, cursor, and custom tools.
*   **[Touch and Pen Input](docs/touch-and-pen.md):** Native touch navigation, gesture arbitration, and extension input.
*   **[Diagnostics](docs/diagnostics.md):** How to observe runtime behavior and debug performance.
*   **[Extensibility](docs/extensibility.md):** Registering custom overlays, cursors, and tools.
*   **[API Reference](docs/api-reference.md):** A fast, linked index to the QPane facade.

## License & Philosophy

QPane is **Free and Open Source Software (FOSS)**, distributed under the **GNU General Public License v3.0 or later**.

I believe that robust UI infrastructure should be a public good, not a proprietary product. QPane is designed to be the standard, high-performance viewer for the PySide6 ecosystem. The GPL ensures it remains free forever, and that any optimizations or fixes made to the core engine are shared back to benefit the next developer.

## From the Developer 💖

I hope QPane saves you the months of headache I spent figuring out efficient tiling and responsive rendering! If you'd like to support my work or see what else I'm up to, here are a few links:

- **Buy Me a Coffee**: You can help fuel more projects like this at my [Ko-fi page](https://ko-fi.com/artificial_sweetener).
- **My Website & Socials**: See my art, poetry, and other dev updates at [artificialsweetener.ai](https://artificialsweetener.ai).
- **If you like this project**, it would mean a lot to me if you gave me a star here on Github!! ⭐
