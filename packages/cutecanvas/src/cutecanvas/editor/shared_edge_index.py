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
"""Cache shared-edge discovery over the current preview-processed scene."""

from __future__ import annotations

from collections.abc import Callable

from cutecanvas.scene.mapping_preview import SceneLayerMappingPreview
from cutecanvas.snapping.edge_candidates import OrientedEdgeCandidateProvider
from cutecanvas.snapping.edge_index import OrientedEdgeIndex
from qpane.sdk.scene import SceneDescriptor

from .shared_edge_discovery import SharedEdgeDiscovery


class SharedEdgeDiscoveryIndex:
    """Own discovery invalidation across scene, preview, and scale revisions."""

    def __init__(
        self,
        *,
        candidates: OrientedEdgeCandidateProvider,
        preview: SceneLayerMappingPreview,
        scale: Callable[[], float],
    ) -> None:
        """Bind exact edge, preview, and device-scale sources."""
        self._candidates = candidates
        self._preview = preview
        self._scale = scale
        self._key: tuple[int, int, float] | None = None
        self._discovery: SharedEdgeDiscovery | None = None

    def get(self, scene: SceneDescriptor) -> SharedEdgeDiscovery | None:
        """Return cached discovery for the exact visible scene geometry."""
        scale = self._scale()
        projected_scene = self._preview.process_scene(scene)
        key = id(scene), self._preview.revision(), scale
        if key == self._key:
            return self._discovery
        targets = self._candidates.capture_scene(projected_scene, layers_only=True)
        self._discovery = (
            None
            if targets is None or targets.scene_id != scene.scene_id
            else SharedEdgeDiscovery(
                projected_scene,
                OrientedEdgeIndex.build(
                    targets.edges,
                    scene_units_per_device_pixel=scale,
                ),
                scene_units_per_device_pixel=scale,
                boundary_for=self._candidates.layer_boundary,
            )
        )
        self._key = key
        return self._discovery

    def invalidate(self) -> None:
        """Discard cached discovery after interaction or scene changes."""
        self._key = None
        self._discovery = None


__all__ = ["SharedEdgeDiscoveryIndex"]
