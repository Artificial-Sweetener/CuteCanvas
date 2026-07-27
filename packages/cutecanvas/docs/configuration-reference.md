**← Previous:** [Configuration](configuration.md)

# Configuration Reference

This annotated mapping shows every `Config` field with its shipped default.
Copy only the groups an application needs to change and apply them with
`Config.configure()`.

Enum-backed strings match the public `CacheMode` and `DiagnosticsDomain`
values. Unknown keys and invalid values raise immediately.
`Config.as_dict()` returns the same detached,
JSON-serializable shape for preferences and diagnostics.


```python
config = {
    "cache": {  # Shared QPane budget plus CuteCanvas-owned extension consumers.
        "mode": "auto",  # CacheMode: auto uses system headroom, hard uses budget_mb.
        "headroom_percent": 0.1,  # Auto mode: keep this fraction of total RAM free.
        "headroom_cap_mb": 4096,  # Auto mode: cap reserved headroom in MB.
        "budget_mb": None,  # Hard mode budget in MB; None -> default 1024, ignored in auto.
        "weights": {  # Relative weights used to split the active cache budget.
            "tiles": 55.0,  # Weight for QPane tile products.
            "pyramids": 45.0,  # Weight for QPane pyramid products.
            "extensions": {
                "mask_overlays": 50.0,  # CuteCanvas coverage presentation products.
                "models": 10.0,  # Optional model and predictor products.
            },
        },
        "prefetch": {  # Neighbor prefetch depths for background warmup.
            "pyramids": 2,  # Neighbor pyramid prefetch depth; 0 disables, -1 unlimited.
            "tiles": 2,  # Neighbor tile prefetch depth; 0 disables, -1 unlimited.
            "tiles_per_neighbor": 4,  # Max tiles to prefetch per neighbor image.
            "extensions": {
                "scene_sources": -1,  # Warm all sources needed by the active document.
                "source_warmup": 0,  # Do not speculate beyond active sources by default.
            },
        },
        "tiles": {  # Tile cache budget override.
            "mb": -1,  # Per-bucket budget in MB; negative/None uses weighted budget.
        },
        "pyramids": {  # Pyramid cache budget override.
            "mb": -1,  # Per-bucket budget in MB; negative/None uses weighted budget.
        },
        "extensions": {
            "mask_overlays": {
                "mb": -1,  # Negative uses the coordinated weighted budget.
            },
            "models": {
                "mb": -1,  # Negative uses the coordinated weighted budget.
            },
        },
    },
    # --- Viewport & Rendering ---
    "tile_size": "auto",  # Physical-viewport-aware tile edge; positive integers stay exact.
    "tile_overlap": 8,  # Overlap in pixels between tiles to avoid seams.
    "min_view_size_px": 128,  # Smallest pyramid/view size (px) before downsampling stops.
    "canvas_expansion_factor": 1.4,  # Pan margin multiplier (>1 lets you pan past edges).
    "safe_min_zoom": 0.001,  # Absolute minimum zoom clamp, regardless of content.
    "drag_out_enabled": True,  # Global gate for drag-out (disabled if False).
    "normalize_zoom_on_screen_change": False,  # Rebase zoom/pan when screen DPR changes.
    "normalize_zoom_for_one_to_one": False,  # Also rebase when in 1:1 zoom mode.
    "smooth_zoom_enabled": True,  # Animate wheel and double-click zoom transitions.
    "smooth_zoom_duration_ms": 80,  # Normal zoom animation duration.
    "smooth_zoom_burst_duration_ms": 20,  # Duration used for rapid wheel bursts.
    "smooth_zoom_burst_threshold_ms": 25,  # Burst window for rapid wheel ticks.
    "smooth_zoom_use_display_fps": True,  # Prefer monitor refresh rate for animation cadence.
    "smooth_zoom_fallback_fps": 60.0,  # Fallback FPS when display refresh is unavailable.

    # --- Masks & Tools ---
    "default_brush_size": 30,  # Default brush size in pixels.
    "brush_scroll_increment": 5,  # Brush size delta per scroll tick.
    "touch_navigation_enabled": True,  # Enable direct one- and two-finger viewport gestures.
    "touch_paint_enabled": True,  # Allow one-finger mask painting in Brush mode.
    "stylus_paint_enabled": True,  # Route active-pen tablet events directly to Brush mode.
    "pen_pressure_enabled": True,  # Scale active-pen diameter from tablet pressure.
    "pen_pressure_min_ratio": 0.15,  # Minimum pressure diameter ratio; range (0, 1].
    "pen_pressure_gamma": 1.0,  # Positive exponent shaping the pressure curve.
    "palm_rejection_ms": 800,  # Reject single-touch painting after recent pen activity.
    "touch_inertia_enabled": True,  # Continue translation briefly after touch release.
    "touch_inertia_deceleration": 4500.0,  # Kinetic deceleration in physical px/s².
    "mask_undo_limit": 20,  # Max undo steps retained per mask.
    "smart_select_min_size": 5,  # Minimum selection size (px) for smart-select tool.
    "mask_border_enabled": False,  # Draw mask borders.
    "mask_prefetch_enabled": True,  # Allow background mask prefetch on navigation.
    "mask_autosave_enabled": False,  # Enable autosave for masks.
    "mask_autosave_on_creation": True,  # Create blank mask files at mask creation.
    "mask_autosave_debounce_ms": 2000,  # Delay after last change before autosave.
    "mask_autosave_path_template": "./saved_masks/{image_name}-{mask_id}.png",  # Uses {image_name}, {mask_id}.

    # --- Diagnostics ---
    "diagnostics_overlay_enabled": False,  # Master switch for diagnostics overlay.
    "diagnostics_domains_enabled": (),  # Enabled domains (DiagnosticsDomain strings/values).
    "draw_tile_grid": False,  # Debug overlay for tile boundaries.

    # --- SAM (AI Features) ---
    "sam_device": "cpu",  # SAM device string (e.g., "cpu", "cuda", "mps" when available).
    "sam_model_path": None,  # Local checkpoint path; overrides download when set.
    "sam_model_url": "https://github.com/ChaoningZhang/MobileSAM/raw/master/weights/mobile_sam.pt",  # Download URL when path not set.
    "sam_model_hash": None,  # Optional SHA-256 checksum; use "default" for the built-in hash.
    "sam_download_mode": "background",  # One of "blocking", "background", "disabled".
    "sam_prefetch_depth": None,  # Predictor prefetch depth; None inherits cache.prefetch.predictors.
    "sam_cache_limit": 1,  # Max cached SAM predictors/embeddings kept in RAM.
}
```

Execution capacity is supplied separately through `execution_policy`,
`execution_runtime`, or a shared `document_runtime`. It is runtime ownership,
not serializable editor configuration.

## Related Docs
Pair this reference with the narrative guide in [Configuration](configuration.md) to understand when to choose each setting, see [Masks and SAM](masks-and-sam.md) for feature-specific behavior, and check [Diagnostics](diagnostics.md) to interpret the live overlay after you tweak these values.

### Diagnostics Domains Example

Use enum members for autocomplete and pass their values into `Config`:

```python
from cutecanvas import Config, DiagnosticsDomain

config = Config().configure(
    diagnostics_domains_enabled=[
        DiagnosticsDomain.CACHE.value,
        DiagnosticsDomain.SWAP.value,
    ]
)
```

**Continue →** [Documents and Layers](scenes.md)
