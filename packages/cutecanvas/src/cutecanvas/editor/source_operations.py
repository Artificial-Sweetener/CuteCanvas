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
"""Source-type registration for editor conversion alternatives."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from qpane.sdk.scene import LayerSourceReference


@dataclass(frozen=True, slots=True)
class EditorSourceOperations:
    """Advertise source-owned alternatives without duplicating edit owners."""

    rasterize: bool = False
    edit_contents: bool = False


class EditorSourceOperationRegistry:
    """Associate exact source-reference types with conversion alternatives."""

    def __init__(self) -> None:
        """Initialize an empty exact-type registry."""
        self._resolvers: dict[
            type[object],
            Callable[[LayerSourceReference], EditorSourceOperations],
        ] = {}

    def register(
        self,
        source_type: type[object],
        operations: EditorSourceOperations,
    ) -> None:
        """Register one source type exactly once."""
        self.register_resolver(source_type, lambda _source: operations)

    def register_resolver(
        self,
        source_type: type[object],
        resolver: Callable[[LayerSourceReference], EditorSourceOperations],
    ) -> None:
        """Register one source-aware alternative resolver exactly once."""
        if source_type in self._resolvers:
            raise ValueError("editor source operations already registered")
        self._resolvers[source_type] = resolver

    def operations_for(self, source: LayerSourceReference) -> EditorSourceOperations:
        """Return alternatives owned by the source's exact domain."""
        resolver = self._resolvers.get(type(source))
        return EditorSourceOperations() if resolver is None else resolver(source)
