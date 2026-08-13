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

"""Characterize linked inspection across first mount and remount lifecycles."""

from __future__ import annotations

import uuid

import pytest
from PySide6.QtCore import QPointF, QSize
from PySide6.QtGui import QColor, QImage

from cutecanvas import CanvasInspectionGroup, CompositionPolicy
from cutecanvas.document import CanvasDocument
from cutecanvas.presentation import CanvasWorkspace
from qpane.sdk.inspection import InspectionViewState, InspectionZoomMode
from qpane.sdk.rendering import ViewportZoomMode


@pytest.mark.parametrize(
    ("first_size", "second_size"),
    (
        (QSize(640, 480), QSize(640, 480)),
        (QSize(640, 480), QSize(1200, 700)),
    ),
)
def test_unseen_linked_detail_preserves_custom_region_through_remount(
    qapp,
    first_size: QSize,
    second_size: QSize,
) -> None:
    """Keep a non-centered linked region authoritative on every activation."""

    document = CanvasDocument()
    first_id = document.create_composition_from_image(
        _image(first_size, QColor("red")),
        title="First",
    )
    second_id = document.create_composition_from_image(
        _image(second_size, QColor("blue")),
        title="Second",
    )
    workspace = CanvasWorkspace(document=document, features=())
    try:
        workspace.resize(913, 577)
        workspace.show()
        workspace.setInspectionGroups(
            (CanvasInspectionGroup(uuid.uuid4(), (first_id, second_id)),)
        )
        workspace.setSinglePresentation(first_id)
        qapp.processEvents()
        first = workspace.canvasFor(first_id)
        assert first is not None
        first.applyZoom(first.currentZoom() * 2.75)
        first.setPan(QPointF(137.0, -83.0))
        qapp.processEvents()
        established = workspace.session.inspection.state_for(first_id)
        assert established is not None
        assert established.zoom_mode is InspectionZoomMode.CUSTOM
        assert (
            abs(established.region.center_x - 0.5) > 0.01
            or abs(established.region.center_y - 0.5) > 0.01
        )

        workspace.setSinglePresentation(second_id)
        qapp.processEvents()
        second = workspace.canvasFor(second_id)
        assert second is not None
        _assert_custom_state(
            workspace.session.inspection.state_for(second_id),
            established,
        )
        assert second.view().viewport.get_zoom_mode() is ViewportZoomMode.CUSTOM

        workspace.setTabbedPresentation((first_id, second_id))
        workspace.setSinglePresentation(first_id)
        workspace.setSinglePresentation(second_id)
        qapp.processEvents()

        _assert_custom_state(
            workspace.session.inspection.state_for(second_id),
            established,
        )
        assert second.view().viewport.get_zoom_mode() is ViewportZoomMode.CUSTOM
    finally:
        workspace.close()
        document.close()
        qapp.processEvents()


def test_nonremovable_composition_still_owns_its_viewport_geometry(qapp) -> None:
    """Keep structural removal policy out of viewport activation behavior."""

    document = CanvasDocument()
    first_id = document.create_composition_from_image(
        _image(QSize(80, 60), QColor("red"))
    )
    protected_size = QSize(320, 180)
    protected_id = document.create_composition_from_image(
        _image(protected_size, QColor("blue")),
        policy=CompositionPolicy(removable=False),
    )
    workspace = CanvasWorkspace(document=document, features=())
    try:
        workspace.resize(700, 500)
        workspace.show()
        workspace.setSinglePresentation(first_id)
        workspace.setSinglePresentation(protected_id)
        qapp.processEvents()

        protected = workspace.canvasFor(protected_id)
        assert protected is not None
        assert protected.view().viewport.content_size == protected_size
        assert protected.view().viewport.get_zoom_mode() is ViewportZoomMode.FIT
    finally:
        workspace.close()
        document.close()
        qapp.processEvents()


def _assert_custom_state(
    actual: InspectionViewState | None,
    expected: InspectionViewState,
) -> None:
    """Assert normalized inspection without relying on target pixel dimensions."""

    assert actual is not None
    assert actual.zoom_mode is InspectionZoomMode.CUSTOM
    assert actual.region.center_x == pytest.approx(expected.region.center_x)
    assert actual.region.center_y == pytest.approx(expected.region.center_y)
    assert actual.region.span_x == pytest.approx(expected.region.span_x)
    assert actual.region.span_y == pytest.approx(expected.region.span_y)


def _image(size: QSize, color: QColor) -> QImage:
    """Return one opaque source with requested native dimensions."""

    image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(color)
    return image
