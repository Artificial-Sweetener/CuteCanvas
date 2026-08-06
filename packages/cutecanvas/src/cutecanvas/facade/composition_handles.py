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
"""Typed handles for composition-level host workflows."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

from PySide6.QtCore import QRectF, QSize

from ..document import CanvasAnchor, CanvasResamplingMode
from ..types import CompositionEntry, CompositionPolicy, LayerPolicy
from .handles import EditorHandleHost
from .layer_handles import LayerHandle


class CompositionCollection:
    """Resolve composition handles without retaining parallel content state."""

    def __init__(self, host: EditorHandleHost) -> None:
        """Bind the authoritative host facade."""
        self._host = host

    def __iter__(self) -> Iterator[CompositionHandle]:
        """Iterate handles in browser order from one detached snapshot."""
        snapshot = self._host.getCompositionSnapshot()
        return iter(CompositionHandle(self._host, value) for value in snapshot.order)

    def __len__(self) -> int:
        """Return the current composition count."""
        return len(self._host.getCompositionSnapshot().order)

    @property
    def current(self) -> CompositionHandle | None:
        """Return the active composition handle, if any."""
        value = self._host.getCompositionSnapshot().current_composition_id
        return None if value is None else CompositionHandle(self._host, value)

    def get(self, composition_id: uuid.UUID) -> CompositionHandle | None:
        """Return a handle only when ``composition_id`` currently exists."""
        snapshot = self._host.getCompositionSnapshot()
        return (
            CompositionHandle(self._host, composition_id)
            if composition_id in snapshot.compositions
            else None
        )

    def create(
        self,
        bounds: QRectF,
        *,
        title: str = "Untitled",
        policy: CompositionPolicy | None = None,
        fit_view: bool = True,
    ) -> CompositionHandle:
        """Create, activate, and return one independent composition handle."""
        composition_id = self._host.createComposition(
            bounds,
            title=title,
            policy=policy,
            fit_view=fit_view,
        )
        return CompositionHandle(self._host, composition_id)


class CompositionHandle:
    """Identify one composition while resolving all state from its sole owner."""

    def __init__(self, host: EditorHandleHost, composition_id: uuid.UUID) -> None:
        """Bind stable composition identity without caching mutable state."""
        self._host = host
        self._composition_id = composition_id

    @property
    def id(self) -> uuid.UUID:
        """Return stable composition identity."""
        return self._composition_id

    @property
    def state(self) -> CompositionEntry:
        """Return current detached composition state or fail after removal."""
        entry = self._host.getCompositionSnapshot().compositions.get(
            self._composition_id
        )
        if entry is None:
            raise LookupError(f"composition {self._composition_id} no longer exists")
        return entry

    @property
    def is_open(self) -> bool:
        """Return whether this composition owns the active scene."""
        return (
            self._host.getCompositionSnapshot().current_composition_id
            == self._composition_id
        )

    @property
    def layers(self) -> tuple[LayerHandle, ...]:
        """Return typed layer handles in bottom-to-top stack order."""
        return tuple(
            LayerHandle(self._host, self._composition_id, layer.layer_id)
            for layer in self.state.layers
        )

    def open(self) -> None:
        """Make this composition active without changing its contents."""
        self._host.openComposition(self._composition_id)

    def remove(self) -> None:
        """Remove this composition when its host policy permits removal."""
        self._host.removeComposition(self._composition_id)

    def set_policy(self, policy: CompositionPolicy) -> bool:
        """Replace host structural policy for this composition."""
        return self._host.setCompositionPolicy(self._composition_id, policy)

    def resize_bounds(
        self,
        size: QSize,
        *,
        anchor: CanvasAnchor = CanvasAnchor.CENTER,
    ) -> bool:
        """Resize bounds and align content without resampling pixels."""
        return self._host.resizeCanvasBounds(
            self._composition_id,
            size,
            anchor=anchor,
        )

    def resample(
        self,
        size: QSize,
        *,
        mode: CanvasResamplingMode = CanvasResamplingMode.SMOOTH,
    ) -> uuid.UUID:
        """Begin source-aware whole-canvas resampling."""
        return self._host.requestCanvasResampling(
            self._composition_id,
            size,
            mode=mode,
        )

    def crop_to_canvas(self) -> bool:
        """Clip every layer to the current canvas as one history edit."""
        return self._host.cropLayersToCanvas(self._composition_id)

    def layer(self, layer_id: uuid.UUID) -> LayerHandle | None:
        """Return a child handle only when the layer currently exists."""
        return next((layer for layer in self.layers if layer.id == layer_id), None)

    def place_composition(
        self,
        source: CompositionHandle,
        *,
        placement: QRectF | None = None,
        label: str | None = None,
        interaction: LayerPolicy | None = None,
    ) -> LayerHandle | None:
        """Place ``source`` as a live layer in this open composition."""
        if not isinstance(source, CompositionHandle):
            raise TypeError("source must be a CompositionHandle")
        if source._host is not self._host:
            raise ValueError("source must belong to the same CuteCanvas")
        if not self.is_open:
            raise RuntimeError(
                "open the destination composition before placing content"
            )
        layer_id = self._host.placeComposition(
            source.id,
            placement=placement,
            label=label,
            interaction=interaction,
        )
        return (
            None
            if layer_id is None
            else LayerHandle(self._host, self._composition_id, layer_id)
        )


__all__ = ["CompositionCollection", "CompositionHandle"]
