#    CuteCanvas - High-performance layered image editor
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.


"""Narrative copy and quick-reference hints for the CuteCanvas example demo."""

from __future__ import annotations

COMPOSITIONS_HINT = (
    "Each composition contains ordinary ordered layers. Select a row to edit it, "
    "use its checkbox for visibility, drag rows to reorder, and right-click to "
    "duplicate an instance, fork shared content, or open focused properties."
)

EXIT_MESSAGE = "Thanks for trying the CuteCanvas example."

CORE_CHAPTER = (
    "Canvas: launch CuteCanvas(config=..., features=('mask',)), import images as "
    "independent compositions, and navigate them with "
    "compositionIDs()/openComposition(). The demo occasionally reads Config.as_dict for "
    "small UI toggles; most hosts should treat config as set-and-forget. The status bar's zoom % label is "
    "wired directly to CuteCanvas.zoomChanged so you can copy that pattern into your own hosts."
)

MASK_CHAPTER = (
    "Masks: create, import, and export masks, rotate mask order, "
    "and observe mask layers through the composition tree and mask signals. Masks render with the image "
    "content while host overlay hooks remain available for separate annotations. The status bar's "
    "undo/redo counter listens to CuteCanvas.maskUndoStackChanged so you can mirror stack depth "
    "affordances in your own hosts."
)

SAM_CHAPTER = (
    "SAM: when enabled, create Smart selections or Smart masks with a drag, tune predictor/cache controls, "
    "and surface installer guidance if extras are missing. When downloads are enabled, "
    "CuteCanvas preflights the checkpoint and fetches it on demand; connect to "
    "samCheckpointStatusChanged/samCheckpointProgress to mirror readiness and progress in host UI. "
    "Use sam_download_mode to pick blocking/background/disabled behavior, sam_model_path to point at "
    "a local checkpoint, sam_model_url to change the download source, and sam_model_hash to verify "
    "checkpoint integrity (use 'default' for the built-in MobileSAM hash). The launcher lets you "
    "override all three so you can simulate host-provided checkpoints. The status bar mirrors checkpoint "
    "readiness and download progress. Predictor caches are keyed "
    "by device and checkpoint path, and CuteCanvas.samCheckpointReady() can gate predictor requests. "
    "The demo launcher exposes the same download-mode switch so you can feel the trade-offs live. "
    "The config dialog has a SAM tab; background updates apply live while blocking/disabled "
    "changes require a restart. "
    "The default path is "
    "QStandardPaths.AppDataLocation/mobile_sam.pt unless sam_model_path is set."
)

DIAGNOSTICS_CHAPTER = (
    "Diagnostics/Config: toggle diagnosticsOverlayEnabled()/setDiagnosticsDomainEnabled, apply settings via CuteCanvas.applySettings, "
    "pick cache/mask/executor domains in the dialog, and adjust cache and interaction settings grouped by domain. "
    "Cache rows report the raster work CuteCanvas prepares for rendered content."
)

OVERLAY_HOOK_CHAPTER = (
    "Hooks: register overlays, cursors, and tools with CuteCanvas.registerOverlay, "
    "CuteCanvas.registerCursorProvider, and CuteCanvas.registerTool."
)

CUSTOM_TOOL_ENABLED = (
    "Custom tool enabled via CuteCanvas.registerTool and registerCursorProvider."
)

CUSTOM_TOOL_DISABLED = "Custom tool removed; toolbar restored."

CUSTOM_TOOL_APPLIED = "Custom cursor provider applied."

CUSTOM_CURSOR_EDITOR_HINT = (
    "This editor shows how to build a cursor provider for a custom tool mode. "
    "The demo host injects qpane and CUSTOM_MODE. "
    "Define cursor(qpane) -> QCursor|None and click Apply to refresh the tool."
)

CUSTOM_OVERLAY_ENABLED = "Custom overlay enabled via CuteCanvas.registerOverlay; tweak the code and click Apply."

CUSTOM_OVERLAY_DISABLED = "Custom overlay removed."

CUSTOM_OVERLAY_APPLIED = "Custom overlay applied and repainted."

CUSTOM_OVERLAY_EDITOR_HINT = (
    "This editor demonstrates an OverlayState-aware overlay hook for displayed content. "
    "Define draw_overlay(painter, state) and click Apply to repaint the qpane; "
    "state.source_image is the resolved base raster, not a flattened mask export."
)

LENS_DEMO_ENABLED = "Paired cursor/overlay hooks enabled."

LENS_DEMO_DISABLED = "Paired hooks removed; toolbar restored."

LENS_DEMO_APPLIED = "Paired cursor/overlay hook applied."

LENS_EDITOR_HINT = (
    "This combined editor shows how cursor and overlay hooks can collaborate. "
    "The demo host injects qpane and CUSTOM_MODE. "
    "Define cursor(qpane) and draw_overlay(painter, state), then click Apply to experiment."
)

EXTENSION_CHECKLIST = (
    "Extend the demo by adding actions, composition controls, config fields, "
    "or hook examples that use CuteCanvas.registerTool, CuteCanvas.registerOverlay, and "
    "CuteCanvas.registerCursorProvider."
)

PARITY_MAP = (
    "The main demo window is ExampleWindow, with composition, config, and hook "
    "helpers split into small modules. Launch it with examples/cutecanvas_demo.py or the "
    "provided launch scripts."
)


def reference_hints(mask_enabled: bool, sam_enabled: bool) -> list[str]:
    """Return the shortcut hints displayed in the quick-reference dialog."""
    hints = [
        "Ctrl+O or right-click: load images",
        "Left/Right, A/D, or arrow toolbar buttons: switch compositions",
        "Close All: close every removable composition",
        "Zoom field: double-click to edit, enter a percent (for example, 125%), press Enter",
        "Zoom toggle: click Set Fit / Set 1:1 to switch zoom presets",
        "Layers panel: switch compositions, select layers, toggle visibility, and drag rows to reorder",
        "Place Composition: reference another open composition as a live nested layer",
    ]
    if mask_enabled:
        hints.extend(
            [
                "M key: create a mask for the current image",
                "Load Mask: import layers from external files",
                "Digits 1-0: activate mask slots",
                "Mask Up/Down: rotate the mask stack",
                "Mask layer rows: right-click to recolor or delete",
            ]
        )
    if mask_enabled and sam_enabled:
        hints.append("Drag a box in Smart Select or Smart Mask mode to run SAM")
    return hints
