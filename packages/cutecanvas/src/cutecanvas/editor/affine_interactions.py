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

"""Cohesive lifecycle boundary for editor affine interactions."""

from __future__ import annotations

from dataclasses import dataclass

from qpane.sdk.scene import SceneDescriptor

from .shared_edge_interaction import SharedEdgeResizeInteraction
from .transform_coordinator import EditorTransformCoordinator


@dataclass(frozen=True, slots=True)
class EditorAffineInteractions:
    """Group mutually exclusive affine tools behind one installed owner."""

    transform: EditorTransformCoordinator
    shared_edge: SharedEdgeResizeInteraction

    def cancel(self) -> bool:
        """Cancel every affine owner without leaving a partial preview."""
        transform_changed = self.transform.cancel()
        shared_edge_changed = self.shared_edge.cancel()
        return transform_changed or shared_edge_changed

    def synchronize_scene(self, scene: SceneDescriptor | None) -> bool:
        """Clear transient affine state invalidated by a scene change."""
        return self.shared_edge.synchronize_scene(scene)

    def cancel_shared_edge(self) -> bool:
        """Cancel shared-edge state before another affine tool takes ownership."""
        return self.shared_edge.cancel()


__all__ = ["EditorAffineInteractions"]
