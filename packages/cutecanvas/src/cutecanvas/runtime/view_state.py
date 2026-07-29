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
"""CanvasViewState behavior for the CuteCanvas facade."""

from __future__ import annotations

import logging
from contextlib import nullcontext
from math import isclose

from PySide6.QtCore import (
    QPoint,
    QPointF,
    QRectF,
)
from PySide6.QtGui import (
    QScreen,
    QWindow,
)
from qpane.sdk.rendering import ViewportZoomMode

logger = logging.getLogger(__name__)


class CanvasViewStateMixin:
    """Group canvasviewstate facade behavior."""

    def _handle_canvas_resize(self) -> None:
        """Realign resized content without publishing intermediate geometry."""
        binding = self._inspection_binding
        publication_guard = (
            nullcontext() if binding is None else binding.suspend_publication()
        )
        with publication_guard:
            self.view().ensure_view_alignment(force=True)
            if binding is not None:
                binding.refresh_target()
        self.update()
        self.refreshCursor()
        self._emit_viewport_rect_if_changed(force=True)

    def onViewChanged(self):
        """Slot connected to the viewport's viewChanged signal."""
        reused = self.view().handle_viewport_changed()
        if reused:
            cursor_refresh_needed = False
        else:
            self.markDirty()
            self.update()
            cursor_refresh_needed = True
        if cursor_refresh_needed:
            self.refreshCursor()
        self._emit_zoom_snapshot()
        self._emit_viewport_rect_if_changed()
        binding = self._inspection_binding
        if binding is not None:
            binding.publish()

    def _allocate_buffers(self):
        """Calculate buffer properties and tell the renderer to allocate them."""
        self.view().allocate_buffers()

    def physicalViewportRect(self) -> QRectF:
        """Return the current viewport rectangle in physical (device) pixels.

        Useful for tile visibility and rendering alignment.
        """
        return self.view().physical_viewport_rect()

    def panelToImagePoint(self, panel_pos: QPoint) -> QPoint | None:
        """Delegates coordinate conversion to the viewport."""
        return self.view().panel_to_image_point(panel_pos)

    def imageToPanelPoint(self, image_point: QPoint) -> QPointF | None:
        """Delegates coordinate conversion to the viewport."""
        return self.view().image_to_panel_point(image_point)

    def _screen_tracking_enabled(self) -> bool:
        """Return True when zoom normalization across screens is enabled."""
        return bool(getattr(self.settings, "normalize_zoom_on_screen_change", False))

    def _refresh_rate_tracking_enabled(self) -> bool:
        """Return True when smooth zoom should target the display refresh rate."""
        return bool(getattr(self.settings, "smooth_zoom_use_display_fps", True))

    def _screen_tracking_required(self) -> bool:
        """Return True when the window should listen for screen change events."""
        return self._screen_tracking_enabled() or self._refresh_rate_tracking_enabled()

    def _normalize_one_to_one_enabled(self) -> bool:
        """Return True when 1:1 zoom normalization is allowed."""
        return bool(getattr(self.settings, "normalize_zoom_for_one_to_one", False))

    def _viewport_in_one_to_one(self, viewport) -> bool:
        """Return True when ``viewport`` currently represents a 1:1 zoom."""
        zoom_mode = viewport.get_zoom_mode()
        if zoom_mode == ViewportZoomMode.ONE_TO_ONE:
            return True
        native_zoom = float(viewport.nativeZoom())
        if native_zoom <= 0:
            return False
        return isclose(viewport.zoom, native_zoom, rel_tol=1e-6, abs_tol=1e-6)

    def _refresh_screen_tracking(self) -> None:
        """Attach or detach screen-change listeners based on the current setting."""
        if not self._screen_tracking_required():
            self._disconnect_screen_signals()
            return
        self._connect_screen_signals()
        if self._tracked_screen is not None:
            self._set_tracked_screen(self._tracked_screen, force=True)

    def _screen_device_pixel_ratio(self, screen: QScreen | None) -> float:
        """Return the DPR for ``screen`` or this qpane when unavailable."""
        if screen is not None:
            ratio = float(screen.devicePixelRatio())
        else:
            ratio = float(self.devicePixelRatioF())
        return ratio if ratio > 0 else 1.0

    def _safe_disconnect(self, signal: object, handler: object) -> None:
        """Best-effort disconnect for Qt signals during teardown."""
        try:
            signal.disconnect(handler)
        except (TypeError, RuntimeError, SystemError):
            pass

    def _rebase_zoom_for_screen_change(self, old_dpr: float, new_dpr: float) -> None:
        """Scale zoom/pan so viewport coverage stays stable across DPR changes.

        Args:
            old_dpr: Device pixel ratio before the change.
            new_dpr: Device pixel ratio reported by the new screen.
        """
        if not self._screen_tracking_enabled():
            return
        if old_dpr <= 0 or new_dpr <= 0:
            return
        if isclose(old_dpr, new_dpr, rel_tol=1e-6, abs_tol=1e-6):
            return
        view = self.view()
        viewport = view.viewport
        if not self._normalize_one_to_one_enabled() and self._viewport_in_one_to_one(
            viewport
        ):
            self._last_screen_dpr = new_dpr
            return
        scale = new_dpr / old_dpr
        new_zoom = viewport.zoom * scale
        pan = viewport.pan
        scaled_pan = QPointF(pan.x() * scale, pan.y() * scale)
        viewport.setZoomAndPan(new_zoom, scaled_pan)
        view.presenter.ensure_view_alignment(force=True)
        self._last_screen_dpr = new_dpr

    def _connect_screen_signals(self) -> None:
        """Ensure the window and active screen notify us about DPR changes."""
        window = self._resolve_window_handle()
        if window is None:
            return
        if self._tracked_window is not window:
            self._disconnect_window_signals()
            window.screenChanged.connect(self._handle_screen_changed)
            window.destroyed.connect(self._handle_tracked_window_destroyed)
            self._tracked_window = window
        self._set_tracked_screen(window.screen())

    def _resolve_window_handle(self) -> QWindow | None:
        """Return the top-level window handle hosting this widget."""
        handle = self.windowHandle()
        if handle is not None:
            return handle
        window = self.window()
        if window is None:
            return None
        return window.windowHandle()

    def _disconnect_screen_signals(self) -> None:
        """Detach all screen tracking hooks."""
        self._disconnect_window_signals()
        self._set_tracked_screen(None)

    def _disconnect_window_signals(self) -> None:
        """Safely disconnect tracked window change hooks and clear the reference."""
        window = self._tracked_window
        if window is None:
            return
        self._safe_disconnect(window.screenChanged, self._handle_screen_changed)
        self._safe_disconnect(window.destroyed, self._handle_tracked_window_destroyed)
        self._tracked_window = None

    def _set_tracked_screen(
        self, screen: QScreen | None, *, force: bool = False
    ) -> None:
        """Swap the screen DPI listener to ``screen`` when provided."""
        if not force and self._tracked_screen is screen:
            return
        if self._tracked_screen is not None:
            if "dpi" in self._tracked_screen_connections:
                self._safe_disconnect(
                    self._tracked_screen.logicalDotsPerInchChanged,
                    self._handle_screen_dpi_changed,
                )
            if "refresh" in self._tracked_screen_connections:
                self._safe_disconnect(
                    self._tracked_screen.refreshRateChanged,
                    self._handle_screen_refresh_rate_changed,
                )
        self._tracked_screen = None
        self._tracked_screen_connections.clear()
        if screen is None:
            return
        if self._screen_tracking_enabled():
            screen.logicalDotsPerInchChanged.connect(self._handle_screen_dpi_changed)
            self._tracked_screen_connections.add("dpi")
        if self._refresh_rate_tracking_enabled():
            screen.refreshRateChanged.connect(self._handle_screen_refresh_rate_changed)
            self._tracked_screen_connections.add("refresh")
        self._tracked_screen = screen
        self._last_screen_dpr = self._screen_device_pixel_ratio(screen)
        self.view().viewport.update_detected_refresh_rate(screen.refreshRate())

    def _handle_tracked_window_destroyed(self, destroyed: object | None = None) -> None:
        """Clear tracked window references when the host window is destroyed."""
        if destroyed is not None and destroyed is not self._tracked_window:
            return
        self._tracked_window = None
        self._set_tracked_screen(None)

    def _handle_screen_changed(self, screen: QScreen | None) -> None:
        """Normalize zoom when the widget moves to a different screen."""
        if self._screen_tracking_enabled():
            old_dpr = self._last_screen_dpr
            new_dpr = self._screen_device_pixel_ratio(screen)
            self._rebase_zoom_for_screen_change(old_dpr, new_dpr)
        self._set_tracked_screen(screen)
        self._emit_viewport_rect_if_changed(force=True)

    def _handle_screen_dpi_changed(self, *_args: object) -> None:
        """Normalize zoom when the current screen updates its DPI."""
        screen = self._tracked_screen
        if not self._screen_tracking_enabled():
            return
        screen = self._tracked_screen
        if screen is None:
            return
        old_dpr = self._last_screen_dpr
        new_dpr = self._screen_device_pixel_ratio(screen)
        self._rebase_zoom_for_screen_change(old_dpr, new_dpr)
        self._last_screen_dpr = new_dpr
        self._emit_viewport_rect_if_changed(force=True)

    def _handle_screen_refresh_rate_changed(self, *_args: object) -> None:
        """Record the latest refresh rate when the screen reports a change."""
        screen = self._tracked_screen
        if screen is None:
            return
        self.view().viewport.update_detected_refresh_rate(screen.refreshRate())

    def _emit_zoom_snapshot(self) -> None:
        """Emit the current zoom factor without reaching into demo code."""
        try:
            zoom = float(self.view().viewport.zoom)
        except RuntimeError:  # pragma: no cover - deleted Qt object during shutdown
            return
        self.zoomChanged.emit(zoom)

    def _normalize_zoom_request(
        self, requested_zoom: float, *, reinterpret_one_as_native: bool = True
    ) -> float | None:
        """Validate and clamp a zoom request for viewport application."""
        viewport = self.view().viewport
        if not self._can_apply_zoom():
            return None
        # Reinterpret '1.0' as nativeZoom() for DPI-accuracy.
        if reinterpret_one_as_native and abs(requested_zoom - 1.0) < 1e-6:
            requested_zoom = self.nativeZoom()
        return viewport.clamp_zoom(requested_zoom)

    def _can_apply_zoom(self) -> bool:
        """Return True when zoom updates are allowed for the current view."""
        viewport = self.view().viewport
        if not self.view().has_renderable_content():
            logger.warning("applyZoom ignored because no image is loaded")
            return False
        if viewport.is_locked():
            logger.warning("applyZoom ignored because the viewport is locked")
            return False
        return True
