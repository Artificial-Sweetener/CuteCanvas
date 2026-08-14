#    QPane + CuteCanvas - High-performance PySide6 rendering and editing
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
"""Protect independent QPane and CuteCanvas semantic-version lineages."""

from __future__ import annotations

import pytest

import tools.check_python_release as release_check
from tools.release.products import python_release_from_tag, release_from_tag
from tools.release.pypi import has_compatible_release


def _release_absent(_name: str, _version: str) -> bool:
    """Represent an immutable package version that is absent from PyPI."""
    return False


@pytest.mark.parametrize(
    ("tag", "product", "version"),
    [
        ("qpane-v3.0.0", "qpane", (3, 0, 0)),
        ("qpane-v4.2.1", "qpane", (4, 2, 1)),
        ("cutecanvas-v1.0.0", "cutecanvas", (1, 0, 0)),
        ("cutecanvas-v2.3.4", "cutecanvas", (2, 3, 4)),
        ("ferrastra-v1.0.0", "ferrastra", (1, 0, 0)),
        ("ferrastra-v1.2.3", "ferrastra", (1, 2, 3)),
    ],
)
def test_product_tags_resolve_independent_stable_versions(
    tag: str,
    product: str,
    version: tuple[int, int, int],
) -> None:
    """Resolve each supported product without consulting sibling tags."""
    resolved, resolved_version = release_from_tag(tag)
    assert resolved.name == product
    assert resolved_version == version


@pytest.mark.parametrize(
    "tag",
    [
        "v3.0.0",
        "qpane-v2.1.2",
        "cutecanvas-v0.9.0",
        "qpane-v3.0",
        "cutecanvas-v1.0.0rc1",
        "ferrastra-v0.0.1",
        "ferrastra-v0.9.9",
    ],
)
def test_invalid_or_regressive_python_release_tags_are_rejected(tag: str) -> None:
    """Reject ambiguous, incomplete, prerelease, and regressive tags."""
    with pytest.raises(ValueError, match="release"):
        release_from_tag(tag)


def test_python_release_admission_rejects_ferrastra_tags() -> None:
    """Keep native-wheel admission separate from Python-only validation."""
    with pytest.raises(ValueError, match="Python release tag"):
        python_release_from_tag("ferrastra-v1.0.0")


def test_release_dependency_requires_a_published_compatible_major() -> None:
    """Admit downstream publication only after its supported line exists."""
    assert not has_compatible_release(((0, 1, 0), (2, 0, 0)), ">=1.0.0,<2.0.0")
    assert has_compatible_release(((0, 1, 0), (1, 0, 0)), ">=1.0.0,<2.0.0")
    assert has_compatible_release(((1, 9, 2),), ">=1.0.0,<2.0.0")


def test_qpane_publication_rejects_an_unresolvable_ferrastra_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stop downstream publication when PyPI cannot satisfy its upstream range."""
    monkeypatch.setattr(release_check, "release_exists", _release_absent)

    def incompatible_versions(name: str) -> tuple[tuple[int, int, int], ...]:
        """Expose only the pre-1.0 Ferrastra line to release admission."""
        assert name == "ferrastra"
        return ((0, 1, 0),)

    monkeypatch.setattr(
        release_check,
        "published_stable_versions",
        incompatible_versions,
    )
    with pytest.raises(RuntimeError, match=r"ferrastra>=1\.0\.0,<2\.0\.0"):
        release_check.run("qpane-v3.0.2", check_pypi=True)


def test_cutecanvas_publication_requires_the_complete_resolvable_stack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Admit CuteCanvas only when both exact upstream lines exist on PyPI."""
    monkeypatch.setattr(release_check, "release_exists", _release_absent)

    def compatible_versions(name: str) -> tuple[tuple[int, int, int], ...]:
        """Expose one compatible release for each upstream product."""
        return {"ferrastra": ((1, 0, 0),), "qpane": ((3, 0, 2),)}[name]

    monkeypatch.setattr(
        release_check,
        "published_stable_versions",
        compatible_versions,
    )
    release_check.run("cutecanvas-v1.0.3", check_pypi=True)
