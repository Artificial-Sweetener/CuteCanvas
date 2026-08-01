#    QPane - High-performance PySide6 image viewer
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
"""Restrained live settings dialog for the QPane viewer example."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from qpane import Config

_IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff)"


class ViewerSettingsDialog(QDialog):
    """Edit the viewer's opinionated defaults without exposing editor policy."""

    def __init__(
        self,
        config: Config,
        diagnostic_domains: tuple[str, ...],
        parent: QWidget | None = None,
    ) -> None:
        """Build focused interaction, performance, and placeholder sections."""
        super().__init__(parent)
        self.setWindowTitle("QPane Settings")
        self.setModal(True)
        self.resize(540, 430)
        self._diagnostic_domains = diagnostic_domains
        self._domain_checks: dict[str, QCheckBox] = {}
        self._tabs = QTabWidget(self)
        self._tabs.addTab(self._build_interaction_tab(), "Interaction")
        self._tabs.addTab(self._build_performance_tab(), "Performance")
        self._tabs.addTab(self._build_placeholder_tab(), "Empty Viewer")
        self._tabs.addTab(self._build_diagnostics_tab(), "Diagnostics")
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.RestoreDefaults
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Ok,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        defaults = buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults)
        defaults.clicked.connect(lambda: self._populate(Config()))
        layout = QVBoxLayout(self)
        layout.addWidget(self._tabs)
        layout.addWidget(buttons)
        self._populate(config)

    def config(self, base: Config) -> Config:
        """Return a validated detached snapshot containing the edited values."""
        candidate = base.copy()
        candidate.configure(
            smooth_zoom_enabled=self.smooth_zoom.isChecked(),
            smooth_zoom_duration_ms=self.smooth_duration.value(),
            touch_navigation_enabled=self.touch_navigation.isChecked(),
            touch_inertia_enabled=self.touch_inertia.isChecked(),
            drag_out_enabled=self.drag_out.isChecked(),
            draw_tile_grid=self.tile_grid.isChecked(),
            tile_size=(
                "auto"
                if self.tile_size_mode.currentData() == "auto"
                else self.tile_size.value()
            ),
            diagnostics_overlay_enabled=self.diagnostics_overlay.isChecked(),
            diagnostics_domains_enabled=tuple(
                domain
                for domain, checkbox in self._domain_checks.items()
                if checkbox.isChecked()
            ),
            cache={
                "mode": self.cache_mode.currentText(),
                "budget_mb": self.cache_budget.value(),
                "prefetch": {"pyramids": self.prefetch_depth.value()},
            },
            placeholder={
                "source": self.placeholder_path.text().strip() or None,
                "panzoom_enabled": self.placeholder_navigation.isChecked(),
                "drag_out_enabled": self.placeholder_drag_out.isChecked(),
                "zoom_mode": self.placeholder_zoom.currentData(),
                "locked_zoom": self.placeholder_zoom_value.value() / 100.0,
            },
        )
        return candidate

    def _build_interaction_tab(self) -> QWidget:
        """Create navigation controls for the viewer's default tool."""
        tab = QWidget(self)
        form = QFormLayout(tab)
        self.smooth_zoom = QCheckBox("Animate wheel and preset zoom changes")
        self.smooth_duration = QSpinBox()
        self.smooth_duration.setRange(0, 1000)
        self.smooth_duration.setSuffix(" ms")
        self.touch_navigation = QCheckBox("Enable direct touch pan and pinch")
        self.touch_inertia = QCheckBox("Continue touch pans with inertia")
        self.drag_out = QCheckBox("Allow Cursor tool drag-out when content fits")
        form.addRow("Smooth zoom", self.smooth_zoom)
        form.addRow("Animation duration", self.smooth_duration)
        form.addRow("Touch navigation", self.touch_navigation)
        form.addRow("Touch inertia", self.touch_inertia)
        form.addRow("Drag-out", self.drag_out)
        return tab

    def _build_performance_tab(self) -> QWidget:
        """Create bounded cache and neighboring-source controls."""
        tab = QWidget(self)
        form = QFormLayout(tab)
        note = QLabel(
            "QPane builds raster pyramids and tiles off the GUI thread. "
            "These controls tune the shared renderer rather than the demo."
        )
        note.setWordWrap(True)
        self.cache_mode = QComboBox()
        self.cache_mode.addItems(("auto", "hard"))
        self.cache_budget = QSpinBox()
        self.cache_budget.setRange(64, 65_536)
        self.cache_budget.setSuffix(" MB")
        self.prefetch_depth = QSpinBox()
        self.prefetch_depth.setRange(0, 16)
        self.prefetch_depth.setSpecialValueText("Off")
        self.tile_size_mode = QComboBox()
        self.tile_size_mode.addItem("Automatic for viewport", "auto")
        self.tile_size_mode.addItem("Fixed host override", "fixed")
        self.tile_size = QSpinBox()
        self.tile_size.setRange(1, 16_384)
        self.tile_size.setSuffix(" px")
        self.tile_size_mode.currentIndexChanged.connect(
            lambda: self.tile_size.setEnabled(
                self.tile_size_mode.currentData() == "fixed"
            )
        )
        self.tile_grid = QCheckBox("Draw renderer tile boundaries")
        form.addRow(note)
        form.addRow("Cache policy", self.cache_mode)
        form.addRow("Hard cache cap", self.cache_budget)
        form.addRow("Neighbor pyramids", self.prefetch_depth)
        form.addRow("Tile sizing", self.tile_size_mode)
        form.addRow("Fixed tile edge", self.tile_size)
        form.addRow("Tile diagnostics", self.tile_grid)
        return tab

    def _build_placeholder_tab(self) -> QWidget:
        """Create empty-catalog image and interaction policy controls."""
        tab = QWidget(self)
        form = QFormLayout(tab)
        self.placeholder_path = QLineEdit()
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_placeholder)
        path_row = QWidget(tab)
        path_layout = QHBoxLayout(path_row)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.addWidget(self.placeholder_path, 1)
        path_layout.addWidget(browse)
        self.placeholder_navigation = QCheckBox("Allow pan and zoom")
        self.placeholder_drag_out = QCheckBox("Allow Cursor tool drag-out")
        self.placeholder_zoom = QComboBox()
        self.placeholder_zoom.addItem("Fit", "fit")
        self.placeholder_zoom.addItem("Locked zoom", "locked_zoom")
        self.placeholder_zoom_value = QSpinBox()
        self.placeholder_zoom_value.setRange(1, 1000)
        self.placeholder_zoom_value.setSuffix(" %")
        form.addRow("Image", path_row)
        form.addRow("Navigation", self.placeholder_navigation)
        form.addRow("Drag-out", self.placeholder_drag_out)
        form.addRow("Initial size", self.placeholder_zoom)
        form.addRow("Locked zoom", self.placeholder_zoom_value)
        return tab

    def _build_diagnostics_tab(self) -> QWidget:
        """Create live HUD and renderer-domain controls."""
        tab = QWidget(self)
        form = QFormLayout(tab)
        self.diagnostics_overlay = QCheckBox("Show the live diagnostics HUD")
        form.addRow("Overlay", self.diagnostics_overlay)
        for domain in self._diagnostic_domains:
            checkbox = QCheckBox(f"Show {domain} detail rows")
            self._domain_checks[domain] = checkbox
            form.addRow(domain.title(), checkbox)
        return tab

    def _populate(self, config: Config) -> None:
        """Populate every control from one detached settings snapshot."""
        self.smooth_zoom.setChecked(bool(config.smooth_zoom_enabled))
        self.smooth_duration.setValue(int(config.smooth_zoom_duration_ms))
        self.touch_navigation.setChecked(bool(config.touch_navigation_enabled))
        self.touch_inertia.setChecked(bool(config.touch_inertia_enabled))
        self.drag_out.setChecked(bool(config.drag_out_enabled))
        self.tile_grid.setChecked(bool(config.draw_tile_grid))
        self.cache_mode.setCurrentText(str(config.cache.mode))
        self.cache_budget.setValue(int(config.cache.budget_mb or 1024))
        self.prefetch_depth.setValue(max(0, int(config.cache.prefetch.pyramids)))
        automatic_tile_size = config.tile_size == "auto"
        self.tile_size_mode.setCurrentIndex(0 if automatic_tile_size else 1)
        self.tile_size.setValue(1024 if automatic_tile_size else int(config.tile_size))
        self.tile_size.setEnabled(not automatic_tile_size)
        placeholder = config.placeholder
        self.placeholder_path.setText(placeholder.source or "")
        self.placeholder_navigation.setChecked(bool(placeholder.panzoom_enabled))
        self.placeholder_drag_out.setChecked(bool(placeholder.drag_out_enabled))
        zoom_index = self.placeholder_zoom.findData(placeholder.zoom_mode)
        self.placeholder_zoom.setCurrentIndex(max(0, zoom_index))
        self.placeholder_zoom_value.setValue(
            round(float(placeholder.locked_zoom or 1.0) * 100.0)
        )
        self.diagnostics_overlay.setChecked(bool(config.diagnostics_overlay_enabled))
        enabled_domains = set(config.diagnostics_domains_enabled or ())
        for domain, checkbox in self._domain_checks.items():
            checkbox.setChecked(domain in enabled_domains)

    def _browse_placeholder(self) -> None:
        """Select a placeholder path without decoding it in the dialog."""
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            "Choose empty-viewer image",
            self.placeholder_path.text(),
            _IMAGE_FILTER,
        )
        if selected:
            self.placeholder_path.setText(str(Path(selected)))
