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
"""Teach optional tools, cursors, and overlays without bloating the app shell.

An editor host normally keeps extension registration beside the UI that owns
it. ``ExtensionTutorialController`` demonstrates that lifecycle: enable a
small trusted-code example, register only public CuteCanvas hooks, and remove
every owned contribution when the example or window closes.
"""

from __future__ import annotations

import logging
import traceback
from collections.abc import Callable

from cutecanvas import CuteCanvas
from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import (
    QAction,
    QBitmap,
    QColor,
    QCursor,
    QFont,
    QFontMetricsF,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QWidget

from demonstration import demo_text, hooks_examples
from demonstration.custom_tool import build_custom_cursor_tool
from demonstration.hooks_editor import HookEditorWindow

logger = logging.getLogger(__name__)

CUSTOM_TOOL_MODE = "custom"
CUSTOM_OVERLAY_NAME = "custom_overlay"
LENS_TOOL_MODE = "lens"
LENS_OVERLAY_NAME = "lens_overlay"


class ExtensionTutorialController:
    """Own the complete lifecycle of the demo's optional extension examples."""

    def __init__(
        self,
        canvas: CuteCanvas,
        parent: QWidget,
        *,
        set_mode: Callable[[str], None],
        set_status: Callable[[str], None],
        rebuild_toolbars: Callable[[], None],
        refresh_tools: Callable[[], None],
    ) -> None:
        """Retain narrow host callbacks instead of reaching into the window."""
        self._canvas = canvas
        self._parent = parent
        self._set_mode = set_mode
        self._set_status = set_status
        self._rebuild_toolbars = rebuild_toolbars
        self._refresh_tools = refresh_tools
        self._custom_tool_action: QAction | None = None
        self._custom_tool_registered = False
        self._custom_tool_enabled = False
        self._custom_tool_editor: HookEditorWindow | None = None
        self._custom_cursor_registered = False
        self._custom_overlay_enabled = False
        self._custom_overlay_editor: HookEditorWindow | None = None
        self._custom_overlay_registered = False
        self._lens_tool_action: QAction | None = None
        self._lens_tool_registered = False
        self._lens_tool_enabled = False
        self._lens_editor: HookEditorWindow | None = None
        self._lens_cursor_registered = False
        self._lens_overlay_registered = False

    @property
    def custom_tool_action(self) -> QAction | None:
        """Return the action created after the custom tool is registered."""
        return self._custom_tool_action

    @property
    def lens_tool_action(self) -> QAction | None:
        """Return the action created after the lens tool is registered."""
        return self._lens_tool_action

    def handle_custom_tool_toggled(self, enabled: bool) -> None:
        """Enable or disable the custom cursor tool tutorial."""
        if enabled:
            self._enable_custom_tool()
        else:
            self._disable_custom_tool()
        self._refresh_tools()

    def handle_custom_overlay_toggled(self, enabled: bool) -> None:
        """Enable or disable the custom overlay tutorial."""
        if enabled:
            self._enable_custom_overlay()
        else:
            self._disable_custom_overlay()

    def handle_lens_toggled(self, enabled: bool) -> None:
        """Enable or disable the combined cursor-and-overlay lens tutorial."""
        if enabled:
            self._enable_lens()
        else:
            self._disable_lens()
        self._refresh_tools()

    def close(self) -> None:
        """Remove every extension contribution owned by this controller."""
        if self._custom_tool_enabled:
            self._disable_custom_tool()
        if self._custom_overlay_enabled:
            self._disable_custom_overlay()
        if self._lens_tool_enabled:
            self._disable_lens()

    def _enable_custom_tool(self) -> None:
        """Register the custom tool and open its live code editor."""
        self._ensure_custom_tool_registered()
        code, error = hooks_examples.load_custom_cursor_example()
        self._ensure_custom_tool_editor(code)
        assert self._custom_tool_editor is not None
        self._show_editor(self._custom_tool_editor, code)
        if error:
            self._set_status(error)
            self._custom_tool_enabled = True
            return
        success, message = self._apply_custom_cursor_code(code)
        if success:
            self._set_mode(CUSTOM_TOOL_MODE)
            self._set_status(demo_text.CUSTOM_TOOL_ENABLED)
        else:
            self._set_status(message)
        self._custom_tool_enabled = True

    def _disable_custom_tool(self) -> None:
        """Unregister the custom tool, cursor, action, and editor."""
        if self._canvas.getControlMode() == CUSTOM_TOOL_MODE:
            self._set_mode(CuteCanvas.CONTROL_MODE_CURSOR)
        if self._custom_cursor_registered:
            self._canvas.unregisterCursorProvider(CUSTOM_TOOL_MODE)
            self._custom_cursor_registered = False
        if self._custom_tool_registered:
            try:
                self._canvas.unregisterTool(CUSTOM_TOOL_MODE)
                self._custom_tool_registered = False
            except RuntimeError:
                logger.exception("Custom tool unregistration failed")
        self._custom_tool_enabled = False
        self._custom_tool_action = None
        self._rebuild_toolbars()
        self._custom_tool_editor = self._close_editor(self._custom_tool_editor)
        self._set_status(demo_text.CUSTOM_TOOL_DISABLED)

    def _apply_custom_cursor_code(self, code: str) -> tuple[bool, str]:
        """Compile and register the custom cursor provider hook."""
        self._ensure_custom_tool_registered()
        sandbox: dict[str, object] = {
            "__builtins__": __builtins__,
            "Qt": Qt,
            "QPoint": QPoint,
            "QRectF": QRectF,
            "QSize": QSize,
            "QBitmap": QBitmap,
            "QColor": QColor,
            "QCursor": QCursor,
            "QFont": QFont,
            "QFontMetricsF": QFontMetricsF,
            "QImage": QImage,
            "QPainter": QPainter,
            "QPen": QPen,
            "QPixmap": QPixmap,
            "CUSTOM_MODE": CUSTOM_TOOL_MODE,
        }
        error = self._execute(code, sandbox, "<cutecanvas-custom-cursor>")
        if error is not None:
            return False, error
        provider = sandbox.get("cursor")
        if not callable(provider):
            return (
                False,
                "Define a function named 'cursor(qpane)' that returns a QCursor.",
            )
        self._canvas.unregisterCursorProvider(CUSTOM_TOOL_MODE)
        self._canvas.registerCursorProvider(CUSTOM_TOOL_MODE, provider)  # type: ignore[arg-type]
        self._custom_cursor_registered = True
        return True, demo_text.CUSTOM_TOOL_APPLIED

    def _ensure_custom_tool_registered(self) -> None:
        """Register the custom tool and its toolbar action once."""
        if not self._custom_tool_registered:
            try:
                self._canvas.registerTool(
                    CUSTOM_TOOL_MODE,
                    build_custom_cursor_tool(self._canvas),
                )
            except ValueError:
                logger.info("Custom tool already registered; continuing")
            self._custom_tool_registered = True
        if self._custom_tool_action is None:
            action = QAction("Custom", self._parent, checkable=True)
            action.triggered.connect(lambda: self._set_mode(CUSTOM_TOOL_MODE))
            self._custom_tool_action = action
            self._rebuild_toolbars()

    def _ensure_custom_tool_editor(self, seed_code: str) -> None:
        """Create the custom cursor editor only when requested."""
        if self._custom_tool_editor is None:
            self._custom_tool_editor = HookEditorWindow(
                "Custom Cursor Editor",
                demo_text.CUSTOM_CURSOR_EDITOR_HINT,
                seed_code,
                self._apply_custom_cursor_code,
                parent=self._parent,
            )

    def _enable_custom_overlay(self) -> None:
        """Register the custom overlay and open its live editor."""
        code, error = hooks_examples.load_custom_overlay_example()
        self._ensure_custom_overlay_editor(code)
        assert self._custom_overlay_editor is not None
        self._show_editor(self._custom_overlay_editor, code)
        if error:
            self._set_status(error)
            self._custom_overlay_enabled = True
            return
        success, message = self._apply_custom_overlay_code(code)
        self._custom_overlay_enabled = True
        self._set_status(demo_text.CUSTOM_OVERLAY_ENABLED if success else message)

    def _disable_custom_overlay(self) -> None:
        """Unregister the custom overlay and close its editor."""
        if self._custom_overlay_registered:
            self._canvas.unregisterOverlay(CUSTOM_OVERLAY_NAME)
            self._custom_overlay_registered = False
        self._custom_overlay_enabled = False
        self._custom_overlay_editor = self._close_editor(self._custom_overlay_editor)
        self._set_status(demo_text.CUSTOM_OVERLAY_DISABLED)

    def _apply_custom_overlay_code(self, code: str) -> tuple[bool, str]:
        """Compile and register the custom overlay draw hook."""
        sandbox: dict[str, object] = {
            "__builtins__": __builtins__,
            "Qt": Qt,
            "QRect": QRect,
            "QColor": QColor,
            "QFont": QFont,
            "QLinearGradient": QLinearGradient,
        }
        error = self._execute(code, sandbox, "<cutecanvas-custom-overlay>")
        if error is not None:
            return False, error
        draw_fn = sandbox.get("draw_overlay")
        if not callable(draw_fn):
            return False, "Define a function named 'draw_overlay(painter, state)'."
        self._canvas.unregisterOverlay(CUSTOM_OVERLAY_NAME)
        self._canvas.registerOverlay(CUSTOM_OVERLAY_NAME, draw_fn)  # type: ignore[arg-type]
        self._custom_overlay_registered = True
        self._canvas.update()
        return True, demo_text.CUSTOM_OVERLAY_APPLIED

    def _ensure_custom_overlay_editor(self, seed_code: str) -> None:
        """Create the custom overlay editor only when requested."""
        if self._custom_overlay_editor is None:
            self._custom_overlay_editor = HookEditorWindow(
                "Custom Overlay Editor",
                demo_text.CUSTOM_OVERLAY_EDITOR_HINT,
                seed_code,
                self._apply_custom_overlay_code,
                parent=self._parent,
            )

    def _enable_lens(self) -> None:
        """Register the lens tool, cursor, overlay, and live editor."""
        self._ensure_lens_tool_registered()
        code, error = hooks_examples.load_lens_example()
        self._ensure_lens_editor(code)
        assert self._lens_editor is not None
        self._show_editor(self._lens_editor, code)
        if error:
            self._set_status(error)
            self._lens_tool_enabled = True
            return
        success, message = self._apply_lens_code(code)
        if success:
            self._set_mode(LENS_TOOL_MODE)
            self._set_status(demo_text.LENS_DEMO_ENABLED)
        else:
            self._set_status(message)
        self._lens_tool_enabled = True

    def _disable_lens(self) -> None:
        """Unregister the lens tool and every contribution it owns."""
        if self._canvas.getControlMode() == LENS_TOOL_MODE:
            self._set_mode(CuteCanvas.CONTROL_MODE_CURSOR)
        if self._lens_cursor_registered:
            self._canvas.unregisterCursorProvider(LENS_TOOL_MODE)
            self._lens_cursor_registered = False
        if self._lens_overlay_registered:
            self._canvas.unregisterOverlay(LENS_OVERLAY_NAME)
            self._lens_overlay_registered = False
        if self._lens_tool_registered:
            try:
                self._canvas.unregisterTool(LENS_TOOL_MODE)
                self._lens_tool_registered = False
            except RuntimeError:
                logger.exception("Lens tool unregistration failed")
        self._lens_tool_enabled = False
        self._lens_tool_action = None
        self._rebuild_toolbars()
        self._lens_editor = self._close_editor(self._lens_editor)
        self._canvas.update()
        self._set_status(demo_text.LENS_DEMO_DISABLED)

    def _apply_lens_code(self, code: str) -> tuple[bool, str]:
        """Compile and register the combined lens cursor and overlay hooks."""
        self._ensure_lens_tool_registered()
        sandbox: dict[str, object] = {
            "__builtins__": __builtins__,
            "Qt": Qt,
            "QPoint": QPoint,
            "QRect": QRect,
            "QColor": QColor,
            "QCursor": QCursor,
            "QFont": QFont,
            "QImage": QImage,
            "QPainter": QPainter,
            "QPainterPath": QPainterPath,
            "QPen": QPen,
            "QPixmap": QPixmap,
            "QSize": QSize,
            "CUSTOM_MODE": LENS_TOOL_MODE,
            "qpane": self._canvas,
        }
        error = self._execute(code, sandbox, "<cutecanvas-lens-tool>")
        if error is not None:
            return False, error
        cursor_provider = sandbox.get("cursor")
        overlay_fn = sandbox.get("draw_overlay")
        if not callable(cursor_provider):
            return (
                False,
                "Define a function named 'cursor(qpane)' that returns a QCursor.",
            )
        if not callable(overlay_fn):
            return False, "Define a function named 'draw_overlay(painter, state)'."
        self._canvas.unregisterCursorProvider(LENS_TOOL_MODE)
        self._canvas.registerCursorProvider(LENS_TOOL_MODE, cursor_provider)  # type: ignore[arg-type]
        self._lens_cursor_registered = True
        self._canvas.unregisterOverlay(LENS_OVERLAY_NAME)
        self._canvas.registerOverlay(LENS_OVERLAY_NAME, overlay_fn)  # type: ignore[arg-type]
        self._lens_overlay_registered = True
        self._canvas.update()
        return True, demo_text.LENS_DEMO_APPLIED

    def _ensure_lens_tool_registered(self) -> None:
        """Register the combined lens tool and toolbar action once."""
        if not self._lens_tool_registered:
            try:
                self._canvas.registerTool(
                    LENS_TOOL_MODE,
                    build_custom_cursor_tool(self._canvas),
                )
            except ValueError:
                logger.info("Lens tool already registered; continuing")
            self._lens_tool_registered = True
        if self._lens_tool_action is None:
            action = QAction("Lens", self._parent, checkable=True)
            action.triggered.connect(lambda: self._set_mode(LENS_TOOL_MODE))
            self._lens_tool_action = action
            self._rebuild_toolbars()

    def _ensure_lens_editor(self, seed_code: str) -> None:
        """Create the combined lens editor only when requested."""
        if self._lens_editor is None:
            self._lens_editor = HookEditorWindow(
                "Cursor + Overlay Editor",
                demo_text.LENS_EDITOR_HINT,
                seed_code,
                self._apply_lens_code,
                parent=self._parent,
            )

    @staticmethod
    def _show_editor(editor: HookEditorWindow, code: str) -> None:
        """Refresh and focus one live extension editor."""
        editor.set_code(code)
        editor.show()
        editor.raise_()
        editor.activateWindow()

    @staticmethod
    def _close_editor(editor: HookEditorWindow | None) -> None:
        """Close one optional editor and return its cleared state."""
        if editor is not None:
            editor.close()

    @staticmethod
    def _execute(
        code: str,
        sandbox: dict[str, object],
        source_name: str,
    ) -> str | None:
        """Run one bundled trusted tutorial and format failures for the status bar."""
        try:
            hooks_examples.execute_trusted_extension(
                code,
                sandbox,
                source_name=source_name,
            )
        except Exception:
            logger.exception("Extension tutorial code failed to execute")
            return f"Error applying extension code:\n{traceback.format_exc(limit=1)}"
        return None
