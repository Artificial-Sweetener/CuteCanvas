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
"""Declarative scene construction for the QPane viewer example."""

from __future__ import annotations

import math
import uuid

from PySide6.QtCore import QObject, QPointF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter
from qpane import (
    BilinearLayerTransform,
    ComparisonOrientation,
    LayerTransform,
    PiecewiseLayerTransform,
    ProjectiveLayerTransform,
    QPane,
    RasterBounds,
    RasterSource,
    RenderLayer,
    RenderScene,
    VectorDocument,
    VectorObject,
    VectorObjectKind,
    VectorShapeKind,
    VectorSource,
    VectorStyle,
    ViewerCatalog,
)


class ViewerSceneController(QObject):
    """Translate host catalog intent into immutable public QPane scenes."""

    presentationChanged = Signal(str)

    def __init__(
        self,
        pane: QPane,
        catalog: ViewerCatalog,
        parent: QObject | None = None,
    ) -> None:
        """Retain the viewer and catalog without duplicating renderer state."""
        super().__init__(parent)
        self._pane = pane
        self._catalog = catalog

    @property
    def comparison_active(self) -> bool:
        """Return whether the current scene is a two-image comparison."""
        return self._pane.comparisonState().enabled

    @property
    def comparison_orientation(self) -> ComparisonOrientation:
        """Return the active comparison split direction."""
        return self._pane.comparisonState().orientation

    def compare_with_next(self) -> bool:
        """Compare the active image with its next catalog neighbor."""
        entries = self._catalog.entries
        index = self._catalog.current_index
        if len(entries) < 2 or index < 0:
            return False
        self._pane.setComparisonPair(
            entries[index].entry_id,
            entries[(index + 1) % len(entries)].entry_id,
        )
        self.presentationChanged.emit("comparison")
        return True

    def flip_comparison(self) -> bool:
        """Switch the comparison between vertical and horizontal reveals."""
        state = self._pane.comparisonState()
        if not state.enabled:
            return False
        orientation = (
            ComparisonOrientation.HORIZONTAL
            if state.orientation is ComparisonOrientation.VERTICAL
            else ComparisonOrientation.VERTICAL
        )
        self._pane.setComparisonSplit(state.split_position, orientation)
        self.presentationChanged.emit("comparison")
        return True

    def clear_comparison(self) -> None:
        """Return from comparison to the active catalog image."""
        self._pane.clearComparison()
        self.presentationChanged.emit("image")

    def compose_contact_sheet(self) -> bool:
        """Arrange every catalog source without merging or copying its pixels."""
        entries = self._catalog.entries
        if not entries:
            return False
        columns = min(3, len(entries))
        rows = math.ceil(len(entries) / columns)
        cell_width = 960
        cell_height = 640
        margin = 48
        layers: list[RenderLayer] = []
        for index, entry in enumerate(entries):
            column = index % columns
            row = index // columns
            available_width = cell_width - margin * 2
            available_height = cell_height - margin * 2
            scale = min(
                available_width / entry.size.width(),
                available_height / entry.size.height(),
            )
            width = entry.size.width() * scale
            height = entry.size.height() * scale
            x = column * cell_width + (cell_width - width) / 2.0
            y = row * cell_height + (cell_height - height) / 2.0
            layers.append(
                RenderLayer(
                    entry.source,
                    transform=LayerTransform(
                        m11=scale,
                        m22=scale,
                        dx=x,
                        dy=y,
                    ),
                    label=entry.label,
                )
            )
        self._pane.setScene(
            RenderScene.from_size(
                QSize(columns * cell_width, rows * cell_height),
                tuple(layers),
            )
        )
        self.presentationChanged.emit("contact-sheet")
        return True

    def show_sdk_scene(self) -> None:
        """Show a restrained mixed raster/vector scene as a secondary lesson."""
        canvas_size = QSize(1800, 1080)
        raster = RasterSource.from_image(_sample_background(canvas_size))
        vectors = VectorSource(_sample_vector_document())
        scene = RenderScene.from_size(
            canvas_size,
            (
                RenderLayer(raster, label="Raster source"),
                RenderLayer(
                    vectors,
                    transform=ProjectiveLayerTransform.from_quadrilaterals(
                        (
                            QPointF(0.0, 0.0),
                            QPointF(780.0, 0.0),
                            QPointF(780.0, 510.0),
                            QPointF(0.0, 510.0),
                        ),
                        (
                            QPointF(570.0, 250.0),
                            QPointF(1_350.0, 320.0),
                            QPointF(1_290.0, 830.0),
                            QPointF(510.0, 760.0),
                        ),
                    ),
                    label="Projectively mapped vector source",
                ),
                RenderLayer(
                    vectors,
                    transform=PiecewiseLayerTransform(
                        source_boundary=(
                            QPointF(0.0, 0.0),
                            QPointF(780.0, 0.0),
                            QPointF(780.0, 255.0),
                            QPointF(780.0, 510.0),
                            QPointF(0.0, 510.0),
                        ),
                        target_boundary=(
                            QPointF(90.0, 90.0),
                            QPointF(470.0, 70.0),
                            QPointF(500.0, 220.0),
                            QPointF(440.0, 430.0),
                            QPointF(70.0, 390.0),
                        ),
                    ),
                    opacity=0.72,
                    label="Piecewise mapped vector source",
                ),
                RenderLayer(
                    vectors,
                    transform=BilinearLayerTransform(
                        source_boundary=(
                            QPointF(0.0, 0.0),
                            QPointF(780.0, 0.0),
                            QPointF(780.0, 510.0),
                            QPointF(0.0, 510.0),
                        ),
                        target_boundary=(
                            QPointF(1_430.0, 180.0),
                            QPointF(1_430.0, 180.0),
                            QPointF(1_720.0, 850.0),
                            QPointF(1_050.0, 850.0),
                        ),
                    ),
                    opacity=0.58,
                    label="Joined-edge bilinear vector source",
                ),
            ),
        )
        self._pane.setScene(scene)
        self.presentationChanged.emit("sdk-scene")


def _sample_background(size: QSize) -> QImage:
    """Build the SDK lesson's reusable raster source."""
    image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    gradient = QLinearGradient(0.0, 0.0, float(size.width()), float(size.height()))
    gradient.setColorAt(0.0, QColor(18, 31, 55))
    gradient.setColorAt(0.55, QColor(44, 90, 116))
    gradient.setColorAt(1.0, QColor(212, 141, 102))
    painter = QPainter(image)
    painter.fillRect(image.rect(), gradient)
    painter.end()
    return image


def _sample_vector_document() -> VectorDocument:
    """Build two semantic objects that remain independent of display scale."""
    bounds = RasterBounds(0, 0, 780, 510)
    panel = VectorObject(
        object_id=uuid.uuid4(),
        kind=VectorObjectKind.SHAPE,
        local_bounds=(0.0, 0.0, 780.0, 510.0),
        transform=LayerTransform(),
        style=VectorStyle(
            fill=QColor(248, 250, 255, 215),
            stroke=QColor(255, 255, 255, 245),
            stroke_width=8.0,
        ),
        shape_kind=VectorShapeKind.RECTANGLE,
    )
    accent = VectorObject(
        object_id=uuid.uuid4(),
        kind=VectorObjectKind.SHAPE,
        local_bounds=(195.0, 95.0, 390.0, 320.0),
        transform=LayerTransform(),
        style=VectorStyle(
            fill=QColor(74, 158, 230, 225),
            stroke=QColor(30, 86, 145, 255),
            stroke_width=12.0,
        ),
        shape_kind=VectorShapeKind.ELLIPSE,
    )
    return VectorDocument(uuid.uuid4(), bounds, (panel, accent))
