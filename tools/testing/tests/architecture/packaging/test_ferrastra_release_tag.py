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

import pytest

import tools.check_ferrastra_release_tag as release_check
from tools.check_ferrastra_release_tag import release_tag_error, workspace_version
from tools.release.products import PRODUCTS, parse_stable_version


def test_workspace_version_is_in_ferrastras_stable_public_line() -> None:
    """Read a canonical non-regressive version from the Cargo workspace."""
    assert (
        parse_stable_version(workspace_version()) >= PRODUCTS["ferrastra"].first_release
    )


def test_matching_release_tag_passes() -> None:
    """Accept the exact product-prefixed workspace version."""
    assert release_tag_error("ferrastra-v0.1.0", "0.1.0") is None


def test_mismatched_release_tag_fails() -> None:
    """Reject publishing a tag whose version differs from the artifact."""
    assert release_tag_error("ferrastra-v0.2.0", "0.1.0") == (
        "Ferrastra release tag must be 'ferrastra-v0.1.0', received "
        "'ferrastra-v0.2.0'"
    )


def test_release_admission_rejects_pre_one_stable_tags() -> None:
    """Keep Ferrastra's public lineage at 1.0.0 and later."""
    with pytest.raises(ValueError, match=r"begin at 1\.0\.0"):
        release_check.run("ferrastra-v0.1.0")


def test_release_admission_rejects_existing_pypi_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Never attempt to overwrite an immutable Ferrastra release."""

    def existing_release(_name: str, _version: str) -> bool:
        """Represent an already published immutable package version."""
        return True

    monkeypatch.setattr(release_check, "workspace_version", lambda: "1.0.0")
    monkeypatch.setattr(release_check, "release_exists", existing_release)
    with pytest.raises(SystemExit, match=r"ferrastra==1\.0\.0"):
        release_check.run("ferrastra-v1.0.0", check_pypi=True)
