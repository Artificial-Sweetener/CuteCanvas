#    QPane + CuteCanvas + Ferrastra - Native graphics architecture tooling
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
"""Protect Ferrastra publishing from tag and package version drift."""

from __future__ import annotations

from tools.check_ferrastra_release_tag import release_tag_error, workspace_version


def test_workspace_version_is_the_stage_zero_package_version() -> None:
    """Read the release version from the authoritative Cargo workspace."""
    assert workspace_version() == "0.1.0"


def test_matching_release_tag_passes() -> None:
    """Accept the exact product-prefixed workspace version."""
    assert release_tag_error("ferrastra-v0.1.0", "0.1.0") is None


def test_mismatched_release_tag_fails() -> None:
    """Reject publishing a tag whose version differs from the artifact."""
    assert release_tag_error("ferrastra-v0.2.0", "0.1.0") == (
        "Ferrastra release tag must be 'ferrastra-v0.1.0', received "
        "'ferrastra-v0.2.0'"
    )
