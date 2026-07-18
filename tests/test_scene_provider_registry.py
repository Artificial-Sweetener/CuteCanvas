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

"""Tests for dynamic scene-provider cache revision ownership."""

from __future__ import annotations

from qpane.scene.registry import SceneProviderRegistry


class _RevisionedContributionProvider:
    """Expose a mutable token for registry revision tests."""

    def __init__(self) -> None:
        self.token = 0

    def revision(self) -> int:
        """Return the current provider-owned token."""
        return self.token

    def scene_contribution(self, _base_scene, _image_id):
        """Contribute no layers; only revision behavior matters here."""
        return


def test_registry_revision_tracks_structure_and_provider_state() -> None:
    """Compiled scenes must invalidate for registration and domain changes."""
    registry = SceneProviderRegistry()
    provider = _RevisionedContributionProvider()
    empty_revision = registry.revision()

    registry.register_contribution(provider)
    registered_revision = registry.revision()
    provider.token += 1
    changed_revision = registry.revision()
    registry.unregister_contribution(provider)

    assert registered_revision != empty_revision
    assert changed_revision != registered_revision
    assert registry.revision() != changed_revision
