#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Contracts for open, focused layer-source capability routing."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSize

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


def test_source_type_registers_only_the_capabilities_it_owns() -> None:
    """Adding a future source must not require fake raster or coverage methods."""
    capabilities = LayerSourceCapabilities.create()
    owner = _MetadataOnlyOwner()
    source = _FutureVectorReference(uuid.uuid4())

    capabilities.metadata.register(_FutureVectorReference, owner)

    assert capabilities.metadata.source_size(source) == QSize(640, 480)
    assert capabilities.metadata.source_path(source) is None
    assert capabilities.rasters.owner_for(source) is None
    assert capabilities.hit_tests.owner_for(source) is None
    assert capabilities.coverage.owner_for(source) is None
    assert capabilities.pixel_presentation.owner_for(source) is None


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
