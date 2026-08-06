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

"""Contextual retained-coverage and flood-fill controls for the demo."""

from __future__ import annotations

from cutecanvas import CuteCanvas
from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QLabel,
    QSpinBox,
    QToolBar,
    QWidget,
)


class CoverageControls(QObject):
    """Present only options relevant to the active coverage tool."""

    def __init__(
        self,
        qpane: CuteCanvas,
        toolbar: QToolBar,
        *,
        fill_selection: QAction,
        rasterize_mask: QAction,
        parent: QObject,
    ) -> None:
        """Build compact shape and Paint Bucket controls."""
        super().__init__(parent)
        self._qpane = qpane
        self._toolbar = toolbar
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._shape_widgets: tuple[QWidget | QAction, ...] = self._build_shapes(
            fill_selection,
            rasterize_mask,
        )
        self._bucket_widgets: tuple[QWidget, ...] = self._build_bucket()
        toolbar.hide()

    def sync_mode(self, mode: str) -> None:
        """Show a concise option set for the active coverage tool."""
        shape = mode in {
            CuteCanvas.CONTROL_MODE_SELECT_RECTANGLE,
            CuteCanvas.CONTROL_MODE_SELECT_ELLIPSE,
            CuteCanvas.CONTROL_MODE_SELECT_LASSO,
            CuteCanvas.CONTROL_MODE_MASK_RECTANGLE,
            CuteCanvas.CONTROL_MODE_MASK_ELLIPSE,
            CuteCanvas.CONTROL_MODE_MASK_LASSO,
        }
        bucket = mode == CuteCanvas.CONTROL_MODE_PAINT_BUCKET
        for item in self._shape_widgets:
            item.setVisible(shape)
        for widget in self._bucket_widgets:
            widget.setVisible(bucket)
        self._toolbar.setVisible(shape or bucket)

    def _build_shapes(
        self,
        fill_selection: QAction,
        rasterize_mask: QAction,
    ) -> tuple[QWidget | QAction, ...]:
        """Build retained-shape feather and explicit operation controls."""
        label = QLabel(" Shape · Feather ", self._toolbar)
        feather = QDoubleSpinBox(self._toolbar)
        feather.setRange(0.0, 1000.0)
        feather.setDecimals(1)
        feather.setSuffix(" px")
        feather.setValue(self._qpane.coverageShapeOptions().feather_radius)
        feather.valueChanged.connect(
            lambda value: self._qpane.configureCoverageShapes(feather_radius=value)
        )
        self._toolbar.addWidget(label)
        self._toolbar.addWidget(feather)
        self._toolbar.addAction(fill_selection)
        self._toolbar.addAction(rasterize_mask)
        return label, feather, fill_selection, rasterize_mask

    def _build_bucket(self) -> tuple[QWidget, ...]:
        """Build tolerance, connectivity, and antialias controls."""
        tolerance_value, contiguous_value, antialias_value = (
            self._qpane.paintBucketOptions()
        )
        label = QLabel(" Paint Bucket · Tolerance ", self._toolbar)
        tolerance = QSpinBox(self._toolbar)
        tolerance.setRange(0, 255)
        tolerance.setValue(tolerance_value)
        contiguous = QCheckBox("Contiguous", self._toolbar)
        contiguous.setChecked(contiguous_value)
        antialias = QCheckBox("Antialias", self._toolbar)
        antialias.setChecked(antialias_value)
        tolerance.valueChanged.connect(
            lambda value: self._qpane.configurePaintBucket(tolerance=value)
        )
        contiguous.toggled.connect(
            lambda checked: self._qpane.configurePaintBucket(contiguous=checked)
        )
        antialias.toggled.connect(
            lambda checked: self._qpane.configurePaintBucket(antialias=checked)
        )
        for widget in (label, tolerance, contiguous, antialias):
            self._toolbar.addWidget(widget)
        return label, tolerance, contiguous, antialias
