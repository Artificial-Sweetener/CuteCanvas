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
"""Protect self-contained PyPI descriptions for both Python products."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlparse

from tools.testing.policy import repository_root

_ROOT = repository_root()
_RELATIVE_MARKDOWN_LINK = re.compile(r"\]\((?!https?://|mailto:|#)[^)]+\)")
_RELATIVE_HTML_SOURCE = re.compile(r"(?:src|href)=[\"'](?!https?://|mailto:|#)")
_MARKDOWN_DESTINATION = re.compile(r"!?\[[^\]]+\]\(([^)]+)\)")
_HTML_DESTINATION = re.compile(r"<(?:img|source)[^>]+(?:src|srcset)=[\"']([^\"']+)")
_CENTERED_BADGE_ROW = re.compile(
    r'<p align="center">\n(?:  <a href="[^"]+"><img [^>]+></a>\n)+</p>'
)
_REPOSITORY_URL_PREFIXES = (
    "https://github.com/Artificial-Sweetener/CuteCanvas/blob/main/",
    "https://github.com/Artificial-Sweetener/CuteCanvas/tree/main/",
    "https://raw.githubusercontent.com/Artificial-Sweetener/CuteCanvas/main/",
)


def test_package_readmes_use_public_links_that_render_on_pypi() -> None:
    """Reject repository-relative links from published long descriptions."""
    for package in ("qpane", "cutecanvas", "ferrastra"):
        readme = (_ROOT / f"packages/{package}/README.md").read_text("utf-8")
        assert _RELATIVE_MARKDOWN_LINK.search(readme) is None, package
        assert _RELATIVE_HTML_SOURCE.search(readme) is None, package
        assert "https://github.com/Artificial-Sweetener/CuteCanvas" in readme


def test_cutecanvas_readme_links_to_qpane_package_and_source() -> None:
    """Connect editor users to QPane's independent distribution and guide."""
    readme = (_ROOT / "packages/cutecanvas/README.md").read_text("utf-8")
    assert "https://pypi.org/project/qpane/" in readme
    assert (
        "https://github.com/Artificial-Sweetener/CuteCanvas/blob/main/"
        "packages/qpane/README.md" in readme
    )
    assert "packages/cutecanvas/docs/getting-started.md" in readme
    assert "packages/cutecanvas/docs/api-reference.md" in readme


def test_product_readmes_group_badges_by_distribution_and_runtime() -> None:
    """Keep product badges centered and ordered like sibling repositories."""
    expected_badges = {
        "cutecanvas": (
            "pypi/v/cutecanvas",
            "github/actions/workflow/status",
            "pypi/dm/cutecanvas",
            "python-3.10%2B",
            "PySide6-6.7.3%2B",
            "license-GPL--3.0--or--later",
        ),
        "qpane": (
            "pypi/v/qpane",
            "github/actions/workflow/status",
            "pypi/dm/qpane",
            "python-3.10%2B",
            "PySide6-6.7.3%2B",
            "license-GPL--3.0--or--later",
        ),
        "ferrastra": (
            "phase-3",
            "github/actions/workflow/status",
            "python-3.10%2B",
            "rust-1.93.1",
            "license-GPL--3.0--or--later",
        ),
    }
    for product, badges in expected_badges.items():
        readme = (_ROOT / f"packages/{product}/README.md").read_text("utf-8")
        rows = _CENTERED_BADGE_ROW.findall(readme)
        assert len(rows) == 1, product
        positions = tuple(rows[0].index(badge) for badge in badges)
        assert positions == tuple(sorted(positions)), product


def test_root_readme_is_the_canonical_cutecanvas_package_guide() -> None:
    """Reject drift between the repository guide and PyPI long description."""
    root_readme = (_ROOT / "README.md").read_bytes()
    package_readme = (_ROOT / "packages/cutecanvas/README.md").read_bytes()
    assert package_readme == root_readme


def test_qpane_readme_keeps_its_product_logo_at_the_top() -> None:
    """Keep QPane's established identity on its independently published guide."""
    readme = (_ROOT / "packages/qpane/README.md").read_text("utf-8")
    assert readme.startswith(
        '<p align="center">\n'
        "  <picture>\n"
        '    <source media="(prefers-color-scheme: dark)" '
        'srcset="https://raw.githubusercontent.com/Artificial-Sweetener/'
        'CuteCanvas/main/assets/logos/logo-white.png">\n'
        '    <source media="(prefers-color-scheme: light)" '
        'srcset="https://raw.githubusercontent.com/Artificial-Sweetener/'
        'CuteCanvas/main/assets/logos/logo-black.png">\n'
        '    <img src="https://raw.githubusercontent.com/Artificial-Sweetener/'
        'CuteCanvas/main/assets/logos/logo-black.png" alt="QPane" width="320">'
    )
    assert "**QPane — PySide6 Image Viewer**" not in readme


def test_root_readme_presents_cutecanvas_as_the_repository_identity() -> None:
    """Present the importable editor and its independently useful foundation."""
    readme = (_ROOT / "README.md").read_text("utf-8")
    assert readme.startswith('<h1 align="center">\n  <picture>')
    assert "needed to build an editor for any purpose" in readme
    assert "the editor you put inside your own application" in readme
    assert "## Build the Editor Your Product Needs" in readme
    assert "## CuteCanvas Is Built on QPane" in readme
    assert "QPane is a high-performance image viewer" in readme
    assert "build on the same public rendering SDK CuteCanvas uses" in readme
    assert "Read the QPane README →" in readme
    assert "## Python on Top, Native Work Underneath" in readme
    assert "Lock a source image and expose a focused mask-authoring surface" in readme
    assert "a compact annotation step to a review workstation" in readme
    assert "## The Missing Editor Layer" not in readme
    assert "two ways into the same graphics stack" not in readme
    assert "finished graphics application" not in readme
    assert "plug-in or scripting API" not in readme
    assert "## Developer Experience" in readme
    assert "## Contributing" in readme


def test_public_editor_and_viewer_readmes_keep_engine_details_private() -> None:
    """Describe public viewer and editor workflows without internal engine assembly."""
    for path in (_ROOT / "README.md", _ROOT / "packages/qpane/README.md"):
        assert "Ferrastra" not in path.read_text("utf-8"), path


def test_public_documentation_file_links_resolve() -> None:
    """Reject stale local and repository links from public product guides."""
    documents = (
        _ROOT / "README.md",
        _ROOT / "CONTRIBUTING.md",
        _ROOT / "ROADMAP.md",
        _ROOT / "tools/README.md",
        *(_ROOT / "packages").glob("*/README.md"),
        *(_ROOT / "packages").glob("*/docs/*.md"),
    )
    missing: list[str] = []
    for document in documents:
        text = document.read_text("utf-8")
        destinations = _MARKDOWN_DESTINATION.findall(text)
        destinations.extend(_HTML_DESTINATION.findall(text))
        for destination in destinations:
            target = _documentation_target(document, destination)
            if target is not None and not target.exists():
                missing.append(f"{document.relative_to(_ROOT)} -> {destination}")
    assert missing == []


def _documentation_target(document: Path, destination: str) -> Path | None:
    """Resolve one documentation destination when this repository owns it."""
    plain_destination = unquote(destination.strip("<>").split("#", 1)[0])
    if not plain_destination or plain_destination.startswith(("#", "mailto:")):
        return None
    for prefix in _REPOSITORY_URL_PREFIXES:
        if plain_destination.startswith(prefix):
            return _ROOT / plain_destination.removeprefix(prefix)
    if urlparse(plain_destination).scheme:
        return None
    return document.parent / plain_destination
