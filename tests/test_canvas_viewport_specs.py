#    QPane + CuteCanvas - High-performance PySide6 rendering and editing
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
"""Prove independent responsive views over shared document content."""

from __future__ import annotations

import uuid

import pytest
from cutecanvas import (
    CanvasRenderVariant,
    CanvasViewportInteraction,
    CanvasViewportSource,
    CanvasViewportSpec,
    CuteCanvas,
)
from cutecanvas.document import CanvasDocument
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QImage
from qpane.sdk.rendering import ViewportZoomMode


def _image(width: int = 640, height: int = 480) -> QImage:
    """Return one opaque image with stable aspect ratio."""

    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("royalblue"))
    return image


def test_viewport_source_rejects_cross_document_layer_subsets() -> None:
    """A viewport subset cannot combine unrelated document identities."""

    first = CanvasDocument()
    second = CanvasDocument()
    try:
        first_id = first.create_composition_from_image(_image())
        second_id = second.create_composition_from_image(_image())
        first_layer = first.snapshot().compositions[first_id].layers[0]
        second_layer = second.snapshot().compositions[second_id].layers[0]

        with pytest.raises(ValueError, match="one document"):
            CanvasViewportSource.layer_subset(
                first.content_reference(first_id, layer_id=first_layer.layer_id),
                second.content_reference(second_id, layer_id=second_layer.layer_id),
            )
    finally:
        first.close()
        second.close()


def test_layer_viewport_is_live_and_does_not_mutate_the_composition(qapp) -> None:
    """A neutral mask view updates while sibling and document retain all layers."""

    document = CanvasDocument()
    author = CuteCanvas(document=document, features=("mask",))
    preview = CuteCanvas(
        document=document,
        document_runtime=author.documentRuntime(),
        features=("mask",),
    )
    try:
        composition_id = author.createCompositionFromImage(_image(), title="Source")
        mask_id = author.createBlankMask(_image().size())
        assert mask_id is not None
        snapshot = author.getCompositionSnapshot().compositions[composition_id]
        mask_layer = next(
            layer for layer in snapshot.layers if layer.source_id == mask_id
        )
        preview.setViewportSpec(
            CanvasViewportSpec(
                CanvasViewportSource.content(
                    document.content_reference(
                        composition_id,
                        layer_id=mask_layer.layer_id,
                    )
                ),
                render_variant=CanvasRenderVariant.MASK_COVERAGE,
                interaction=CanvasViewportInteraction.FIT_ONLY,
            )
        )
        preview.resize(320, 240)
        preview.show()
        qapp.processEvents()

        preview_scene = preview.currentScene()
        author_scene = author.currentScene()
        assert preview_scene is not None and author_scene is not None
        assert tuple(layer.layer_id for layer in preview_scene.layers) == (
            mask_layer.layer_id,
        )
        assert len(author_scene.layers) == 2
        assert len(document.snapshot().compositions[composition_id].layers) == 2

        coverage = QImage(_image().size(), QImage.Format.Format_Grayscale8)
        coverage.fill(255)
        assert document.masks.commit_mask_image(mask_id, coverage)
        qapp.processEvents()

        center = preview.grab().toImage().pixelColor(preview.rect().center())
        assert center.red() > 220
        assert abs(center.red() - center.green()) <= 1
        assert abs(center.green() - center.blue()) <= 1
    finally:
        preview.close()
        author.close()
        document.close()


def test_fit_only_view_refits_without_mutating_interactive_sibling(qapp) -> None:
    """Hostile resize refits only the explicitly responsive viewport."""

    document = CanvasDocument()
    interactive = CuteCanvas(document=document, features=())
    responsive = CuteCanvas(
        document=document,
        document_runtime=interactive.documentRuntime(),
        features=(),
    )
    try:
        composition_id = interactive.createCompositionFromImage(_image())
        source = CanvasViewportSource.content(
            document.content_reference(composition_id)
        )
        interactive.setViewportSpec(
            CanvasViewportSpec(
                source,
                viewport_id=uuid.uuid4(),
                interaction=CanvasViewportInteraction.INTERACTIVE,
            )
        )
        responsive.setViewportSpec(
            CanvasViewportSpec(
                source,
                viewport_id=uuid.uuid4(),
                interaction=CanvasViewportInteraction.FIT_ONLY,
            )
        )
        interactive.resize(800, 600)
        responsive.resize(800, 600)
        interactive.show()
        responsive.show()
        qapp.processEvents()
        interactive.view().viewport.zoom_mode = ViewportZoomMode.CUSTOM
        interactive.view().viewport.setZoomAndPan(2.25, QPointF(31.0, -17.0))

        zooms: list[float] = []
        for width, height in (
            (73, 401),
            (1200, 90),
            (81, 79),
            (1024, 768),
            (190, 900),
            (800, 600),
        ):
            responsive.resize(width, height)
            qapp.processEvents()
            zooms.append(responsive.currentZoom())
            assert responsive.view().viewport.get_zoom_mode() is ViewportZoomMode.FIT
            assert responsive.view().viewport.is_locked()

        assert len(set(zooms)) > 2
        assert interactive.currentZoom() == pytest.approx(2.25)
        assert interactive.view().viewport.pan == QPointF(31.0, -17.0)
        assert interactive.viewportSpec() is not None
        assert responsive.viewportSpec() is not None
        assert (
            interactive.viewportSpec().viewport_id
            != responsive.viewportSpec().viewport_id
        )
    finally:
        responsive.close()
        interactive.close()
        document.close()
