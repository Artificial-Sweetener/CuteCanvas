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


"""Assemble the complete CuteCanvas editor tutorial.

The module follows the order an application normally takes: configure and
create the canvas, mount the surrounding Qt interface, connect focused
controllers, then seed a document that invites editing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from cutecanvas import Config, CuteCanvas
from PySide6.QtCore import QByteArray, QEvent, QRect, Qt
from PySide6.QtGui import (
    QIcon,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMainWindow,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from qpane import create_default_execution_runtime

from examples.demo_settings import load_demo_settings, save_demo_window_settings
from examples.demonstration import demo_text
from examples.demonstration.command_tutorial import CommandTutorialController
from examples.demonstration.composition_tutorial import (
    CompositionTutorialController,
)
from examples.demonstration.config.spec import (
    build_sections_for_features,
    field_sets_for_sections,
)
from examples.demonstration.configuration_tutorial import (
    ConfigurationTutorialController,
)
from examples.demonstration.extension_tutorial import ExtensionTutorialController
from examples.demonstration.input_tutorial import ApplicationInputTutorial
from examples.demonstration.presentation_tutorial import (
    PresentationTutorialController,
)
from examples.demonstration.status_tutorial import StatusTutorialController
from examples.demonstration.tool_mode_tutorial import ToolModeTutorialController
from examples.demonstration.welcome_document import seed_welcome_document
from examples.demonstration.workspace_tutorial import WorkspaceTutorialController
from tools.navigation_trace import NavigationTraceRecorder

MASK_KEY_LOOKUP = {
    Qt.Key_1: 0,
    Qt.Key_2: 1,
    Qt.Key_3: 2,
    Qt.Key_4: 3,
    Qt.Key_5: 4,
    Qt.Key_6: 5,
    Qt.Key_7: 6,
    Qt.Key_8: 7,
    Qt.Key_9: 8,
    Qt.Key_0: 9,
}


logger = logging.getLogger(__name__)


@dataclass
class ExampleOptions:
    """CLI options controlling optional SAM and its configuration."""

    sam_enabled: bool = False
    config_strict: bool = False
    log_level: str = "INFO"
    sam_download_mode: str | None = None
    sam_model_path: str | None = None
    sam_model_url: str | None = None
    sam_model_hash: str | None = None
    navigation_trace_output: str | None = None
    navigation_document: str | None = None


class ExampleWindow(QMainWindow):
    """Compose the editor from public CuteCanvas APIs and ordinary Qt UI.

    Tutorial flow:
    - Configure settings and create the CuteCanvas (``_build_qpane``).
    - Wire CuteCanvas signals into UI updates (``_connect_qpane_signals``).
    - Build the layout, status bar, and document panel (``_build_layout``,
      ``_build_status_bar``, ``_build_document_panel``).
    - Create actions, menus, and toolbars (``_create_actions``,
      ``_create_menus``, ``_build_toolbars``).
    - Finalize startup state (``_finalize_startup``).

    The builders below show how a host can wire document snapshots, menus,
    status labels, masks, SAM actions, diagnostics, overlays, cursors, and
    custom tools around a CuteCanvas instance.
    """

    def __init__(self, options: ExampleOptions, *, config: Config | None = None):
        """Assemble the example window in the same order a host would build a CuteCanvas UI."""
        super().__init__()
        self.options = options
        self._example_config = config if config is not None else Config()
        self._execution_runtime = create_default_execution_runtime()
        self._execution_closed = False
        self._reference_dialog: QuickReferenceDialog | None = None
        self._shortcuts: list[QShortcut] = []
        self._navigation_trace: NavigationTraceRecorder | None = None
        self._configure_window_frame()
        self._build_qpane()
        self._configure_dialog_fields()
        self._build_layout()
        self.status_ui = StatusTutorialController(
            self.qpane,
            self,
            masks_available=self._mask_tools_available,
            show_mask_history=self._mask_status_enabled(),
            show_sam=self._sam_tools_available(),
        )
        self.status = self.status_ui.bar
        self.setStatusBar(self.status)
        self.workspace = WorkspaceTutorialController(
            self.qpane,
            self,
            execution_runtime=self._execution_runtime,
            masks_available=self._mask_tools_available,
            set_status=self.status_ui.show_message,
        )
        self.tools = ToolModeTutorialController(
            self.qpane,
            self,
            masks_available=self._mask_tools_available,
            sam_available=self._sam_tools_available,
            create_mask=self.workspace.create_mask_for_current_image,
            show_status=self.status_ui.show_message,
            document_refresh=lambda: (
                self.composition_ui.refresh_selection()
                if hasattr(self, "composition_ui")
                else None
            ),
            extension_actions=lambda: (
                self.extensions.custom_tool_action,
                self.extensions.lens_tool_action,
            ),
        )
        self.qpane.controlModeChanged.connect(self.tools.sync_mode)
        self.extensions = ExtensionTutorialController(
            self.qpane,
            self,
            set_mode=self.tools.set_mode,
            set_status=self.status_ui.show_message,
            rebuild_toolbars=lambda: self.commands.build_toolbar(),
            refresh_tools=lambda: self.commands.refresh_tools(),
        )
        self.configuration = ConfigurationTutorialController(
            self.qpane,
            self,
            self._example_config,
            active_features=self._active_features,
            dialog_fields=self._dialog_all_fields,
            set_status=self.status_ui.show_message,
            refresh_tools=lambda: self.commands.refresh_tools(),
        )
        self.composition_ui = CompositionTutorialController(
            self.qpane,
            self,
            container=self._document_container,
            container_layout=self._document_container_layout,
            splitter=self._splitter,
            container_default_maximum=self._document_container_default_max,
            focus_requested=self.tools.apply_document_focus,
            show_status=self.status_ui.show_message,
        )
        self.presentations = PresentationTutorialController(
            self.qpane,
            self,
            show_status=self.status_ui.show_message,
        )
        self._build_document_panel()
        self.commands = CommandTutorialController(
            self.qpane,
            self,
            workspace=self.workspace,
            tools=self.tools,
            compositions=self.composition_ui,
            configuration=self.configuration,
            extensions=self.extensions,
            masks_available=self._mask_tools_available,
            show_reference=self._show_reference_popover,
            show_presentations=self.presentations.show,
            show_status=self.status_ui.show_message,
            refresh_mask_status=self.status_ui.update_mask_stack,
        )
        self.application_input = ApplicationInputTutorial(
            self.qpane,
            self,
            self.status_ui.zoom_input,
            open_images=self.workspace.open_images_dialog,
            enter_zoom_edit=self.status_ui.enter_zoom_edit,
            apply_zoom_edit=self.status_ui.apply_zoom_input,
            resize_zoom_editor=self.status_ui.resize_zoom_input,
            resize_zoom_toggle=self.status_ui.resize_zoom_toggle,
        )
        self.configuration.apply_detail_preferences({})
        self._connect_qpane_signals()
        self.commands.connect_signals()
        self._install_shortcuts()
        self._finalize_startup()
        self._configure_navigation_trace()

    def _configure_window_frame(self) -> None:
        """Apply the window title and initial sizing."""
        self.setWindowTitle("CuteCanvas Example")
        self.setMinimumSize(1100, 700)
        self._apply_window_icon()
        settings = load_demo_settings()
        window_geometry = settings.get("window_geometry")
        if isinstance(window_geometry, str):
            restored = self._restore_window_geometry(window_geometry)
        else:
            restored = False
        if not restored:
            window_size = settings.get("window_size")
            window_position = settings.get("window_position")
            if isinstance(window_size, tuple):
                self.resize(*window_size)
            else:
                self.resize(1280, 900)
            if isinstance(window_position, tuple):
                self.move(*window_position)

    def _persist_window_geometry(self) -> None:
        """Save the window size and position to the demo settings file."""
        geometry = self._window_geometry_snapshot()
        size = geometry.size()
        position = geometry.topLeft()
        window_geometry = self._encode_window_geometry()
        save_demo_window_settings(
            window_geometry=window_geometry,
            window_size=(size.width(), size.height()),
            window_position=(position.x(), position.y()),
        )

    def _window_geometry_snapshot(self) -> QRect:
        """Return the geometry snapshot to persist."""
        if self.isMaximized() or self.isFullScreen():
            return self.normalGeometry()
        return self.geometry()

    def _encode_window_geometry(self) -> str | None:
        """Return the current window geometry encoded as base64."""
        geometry = self.saveGeometry()
        if geometry.isEmpty():
            return None
        return bytes(geometry.toBase64()).decode("ascii")

    def _restore_window_geometry(self, encoded: str) -> bool:
        """Restore the window geometry from a base64 settings payload."""
        try:
            raw = QByteArray(encoded.encode("ascii"))
        except UnicodeEncodeError:
            return False
        restored = self.restoreGeometry(QByteArray.fromBase64(raw))
        return restored

    def _apply_window_icon(self) -> None:
        """Set the demo window icon when the asset exists on disk."""
        icon_path = (
            Path(__file__).resolve().parents[2] / "assets" / "logos" / "icon-white.png"
        )
        if icon_path.is_file():
            self.setWindowIcon(QIcon(str(icon_path)))

    @staticmethod
    def _feature_names(sam_enabled: bool) -> tuple[str, ...]:
        """Return the standard editor features and optional SAM integration."""
        return ("mask", "sam") if sam_enabled else ("mask",)

    def _mask_tools_available(self) -> bool:
        """Return True when mask tooling is available."""
        return self.qpane.maskFeatureAvailable()

    def _mask_status_enabled(self) -> bool:
        """Return True when the demo should show mask-specific status widgets."""
        return self._mask_tools_available()

    def _sam_tools_available(self) -> bool:
        """Return True when SAM tooling is available."""
        return self.qpane.samFeatureAvailable()

    def _build_qpane(self) -> None:
        """Create the public CuteCanvas facade and capture feature state."""
        feature_names = self._feature_names(self.options.sam_enabled)
        self.qpane = CuteCanvas(
            config=self._example_config.copy(),
            features=feature_names,
            execution_runtime=self._execution_runtime,
            config_strict=self.options.config_strict,
        )
        self.qpane.setFocusPolicy(Qt.StrongFocus)
        self._active_features = tuple(self.qpane.installedFeatures)
        mask_enabled = self._mask_tools_available()
        sam_enabled = self._sam_tools_available()
        self._reference_hints = self._build_reference_hints(mask_enabled, sam_enabled)

    def _configure_dialog_fields(self) -> None:
        """Prepare field metadata used by the config dialog."""
        sections = build_sections_for_features(self._active_features)
        self._dialog_all_fields, _, _ = field_sets_for_sections(sections)

    def _build_layout(self) -> None:
        """Compose the splitter and primary container widgets."""
        self._qpane_container = QWidget(self)
        self._qpane_container_layout = QVBoxLayout(self._qpane_container)
        self._qpane_container_layout.setContentsMargins(0, 0, 0, 0)
        self._qpane_container_layout.setSpacing(0)
        self._qpane_container_layout.addWidget(self.qpane)
        self._document_container = QWidget(self)
        self._document_container_default_max = self._document_container.maximumWidth()
        self._document_container_layout = QVBoxLayout(self._document_container)
        self._document_container_layout.setContentsMargins(0, 0, 0, 0)
        self._document_container_layout.setSpacing(0)
        self._splitter = QSplitter(Qt.Horizontal, self)
        self._splitter.addWidget(self._document_container)
        self._splitter.addWidget(self._qpane_container)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setCollapsible(0, True)
        self.setCentralWidget(self._splitter)
        self._document_container.hide()
        self.installEventFilter(self)

    def _finalize_startup(self) -> None:
        """Complete the final step of demo initialization."""
        if not self.qpane.compositionIDs():
            seed_welcome_document(self.qpane)
        self.commands.prime()
        self.composition_ui.show_initially()
        self.tools.sync_mode(self.qpane.getControlMode())
        self.status_ui.show_message(
            "Starter document ready · select a layer, then move, transform, or paint."
        )
        self.status_ui.prime()

    def _install_shortcuts(self) -> None:
        """Register keyboard shortcuts that drive demo actions."""
        self._shortcuts.clear()

        def _add_shortcut(sequence: QKeySequence, handler) -> None:
            """Register a shortcut and retain it for the window lifetime."""
            shortcut = QShortcut(sequence, self)
            shortcut.activated.connect(handler)
            self._shortcuts.append(shortcut)

        _add_shortcut(
            QKeySequence(Qt.Key_A),
            partial(self.workspace.step_composition, -1),
        )
        _add_shortcut(
            QKeySequence(Qt.Key_D),
            partial(self.workspace.step_composition, 1),
        )
        _add_shortcut(
            QKeySequence(Qt.Key_Backspace),
            self.workspace.remove_current_composition,
        )
        _add_shortcut(
            QKeySequence(Qt.Key_M),
            self.workspace.create_mask_for_current_image,
        )
        for key, index in MASK_KEY_LOOKUP.items():
            _add_shortcut(
                QKeySequence(key),
                partial(self.workspace.select_mask_by_index, index),
            )
        if self.options.navigation_trace_output:
            _add_shortcut(QKeySequence(Qt.Key_F9), self._toggle_navigation_trace)

    def _configure_navigation_trace(self) -> None:
        """Open the requested document and arm opt-in F9 navigation recording."""
        document = (
            None
            if not self.options.navigation_document
            else Path(self.options.navigation_document).resolve()
        )
        if document is not None and not self.workspace.open_composition(document):
            return
        output = self.options.navigation_trace_output
        if not output:
            return
        self._navigation_trace = NavigationTraceRecorder(
            self.qpane,
            Path(output),
            document_path=document,
            status=self.status_ui.show_message,
            parent=self,
        )
        self.status_ui.show_message(
            f"Navigation recorder armed · press F9, reproduce the lag, then press F9 "
            f"again · {self._navigation_trace.output_path}"
        )

    def _toggle_navigation_trace(self) -> None:
        """Toggle the optional navigation recorder."""
        recorder = self._navigation_trace
        if recorder is not None:
            recorder.toggle()

    def _connect_qpane_signals(self) -> None:
        """Wire qpane signals to window/UI slots."""
        self.status_ui.connect_signals()
        self.qpane.diagnosticsOverlayToggled.connect(
            self.configuration.sync_overlay_toggle
        )
        self.qpane.diagnosticsDomainToggled.connect(
            self.configuration.sync_detail_toggle
        )

    def _build_document_panel(self) -> None:
        """Create or refresh the document-and-layer panel."""
        self.composition_ui.build()

    def _build_reference_hints(
        self, mask_enabled: bool, sam_enabled: bool
    ) -> list[str]:
        """Return the shortcut hints displayed in the quick-reference dialog."""
        return demo_text.reference_hints(mask_enabled, sam_enabled)

    def _show_reference_popover(self) -> None:
        """Display or refocus the quick-reference dialog."""
        if self._reference_dialog is None:
            dialog = QuickReferenceDialog(self._reference_hints, self)
            dialog.finished.connect(self._handle_reference_closed)
            self._reference_dialog = dialog
        self._reference_dialog.show()
        self._reference_dialog.raise_()
        self._reference_dialog.activateWindow()

    def _handle_reference_closed(self, _: int) -> None:
        """Clear the reference dialog pointer after it closes."""
        self._reference_dialog = None

    def closeEvent(self, event: QEvent) -> None:
        """Close helper dialogs and emit a farewell message on exit."""
        if self._navigation_trace is not None and self._navigation_trace.active:
            self._navigation_trace.stop()
        if self._reference_dialog is not None:
            self._reference_dialog.close()
        self.application_input.close()
        self.extensions.close()
        self.presentations.close()
        self.status_ui.show_message(demo_text.EXIT_MESSAGE)
        super().closeEvent(event)
        if event.isAccepted():
            self._close_execution()
            self._persist_window_geometry()

    def _close_execution(self) -> None:
        """Close demo-owned scopes before releasing the shared runtime."""
        if self._execution_closed:
            return
        self._execution_closed = True
        self.workspace.close()
        self._execution_runtime.shutdown(wait=False)


class QuickReferenceDialog(QDialog):
    """Floating helper that summarizes the primary demo shortcuts."""

    def __init__(self, hints: list[str], parent: QWidget | None = None) -> None:
        """Render the hint list in a lightweight, non-modal popup."""
        super().__init__(parent)
        self.setWindowTitle("Quick Reference")
        self.setModal(False)
        self.setWindowFlag(Qt.Tool)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        label = QLabel("\n".join(f"- {hint}" for hint in hints), self)
        label.setWordWrap(True)
        layout.addWidget(label)
        buttons = QDialogButtonBox(QDialogButtonBox.Close, parent=self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
