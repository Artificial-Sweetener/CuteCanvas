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
"""Contracts for open, focused layer-source capability routing."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from cutecanvas.scene.source_capabilities import EditorSourceCapabilities
from PySide6.QtCore import QRectF, QSize
from qpane.scene.source_capabilities import LayerSourceCapabilities


@dataclass(frozen=True, slots=True)
class _FutureVectorReference:
    """Represent a future source type unknown to scene infrastructure."""

    vector_id: uuid.UUID

    @property
    def kind(self) -> str:
        """Return a diagnostic and persistence kind."""
        return "future-vector"

    @property
    def resource_id(self) -> uuid.UUID:
        """Return stable source identity."""
        return self.vector_id


class _MetadataOnlyOwner:
    """Supply metadata without implementing unrelated raster capabilities."""

    def source_size(self, source: _FutureVectorReference) -> QSize:
        """Return intrinsic vector bounds for the test source."""
        return QSize(640, 480)

    def source_path(self, source: _FutureVectorReference) -> Path | None:
        """Return no path for an embedded test source."""
        return None


class _ContentBoundsOwner:
    """Return one mutable rectangle to exercise registry detachment."""

    def __init__(self) -> None:
        """Create fractional source geometry."""
        self.bounds = QRectF(0.25, 1.5, 20.75, 30.125)

    def content_bounds(self, source: _FutureVectorReference) -> QRectF:
        """Return the owner-held bounds instance."""
        del source
        return self.bounds


def test_source_type_registers_only_the_capabilities_it_owns() -> None:
    """Adding a future source must not require fake raster or coverage methods."""
    capabilities = LayerSourceCapabilities.create()
    editor_capabilities = EditorSourceCapabilities.create()
    owner = _MetadataOnlyOwner()
    source = _FutureVectorReference(uuid.uuid4())

    capabilities.metadata.register(_FutureVectorReference, owner)

    assert capabilities.metadata.source_size(source) == QSize(640, 480)
    assert capabilities.metadata.source_path(source) is None
    assert capabilities.rasters.owner_for(source) is None
    assert capabilities.hit_tests.owner_for(source) is None
    assert editor_capabilities.coverage.owner_for(source) is None
    assert editor_capabilities.pixel_presentation.owner_for(source) is None


def test_capability_registry_rejects_parallel_owners_for_one_source_type() -> None:
    """One focused capability cannot acquire two authoritative owners."""
    capabilities = LayerSourceCapabilities.create()
    first = _MetadataOnlyOwner()
    second = _MetadataOnlyOwner()
    capabilities.metadata.register(_FutureVectorReference, first)

    try:
        capabilities.metadata.register(_FutureVectorReference, second)
    except ValueError as error:
        assert "already registered" in str(error)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("parallel source capability owners were accepted")


def test_editor_geometry_registry_preserves_fractions_and_detaches_results() -> None:
    """Continuous bounds must cross the capability boundary without aliasing."""
    capabilities = EditorSourceCapabilities.create()
    owner = _ContentBoundsOwner()
    source = _FutureVectorReference(uuid.uuid4())
    capabilities.content_bounds.register(_FutureVectorReference, owner)

    first = capabilities.content_bounds.content_bounds(source)
    assert first == owner.bounds
    assert first is not None
    first.translate(100.0, 100.0)

    assert capabilities.content_bounds.content_bounds(source) == QRectF(
        0.25,
        1.5,
        20.75,
        30.125,
    )
