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
"""Protect the product family's responsive vector identities."""

from __future__ import annotations

from xml.etree import ElementTree

from tools.testing.policy import repository_root

_ROOT = repository_root()
_SVG_NAMESPACE = "{http://www.w3.org/2000/svg}"
_PRODUCT_LOGOS = (
    ("cutecanvas", "0 0 1752 635"),
    ("ferrastra", "0 0 1183 292"),
)


def test_root_readme_mounts_public_theme_specific_cutecanvas_vectors() -> None:
    """Keep the canonical guide branded on GitHub and package indexes."""
    readme = (_ROOT / "README.md").read_text("utf-8")
    base = (
        "https://raw.githubusercontent.com/Artificial-Sweetener/"
        "CuteCanvas/main/assets/logos/cutecanvas-logo"
    )
    assert '<source media="(prefers-color-scheme: dark)"' in readme
    assert f'srcset="{base}-on-dark.svg"' in readme
    assert '<source media="(prefers-color-scheme: light)"' in readme
    assert f'srcset="{base}-on-light.svg"' in readme
    assert 'alt="CuteCanvas — PySide6 Graphics Editor"' in readme
    assert f'src="{base}.svg"' in readme
    assert 'width="760"' in readme


def test_package_readmes_mount_their_absolute_theme_specific_vectors() -> None:
    """Keep published product guides branded without repository-relative URLs."""
    products = (
        ("cutecanvas", "CuteCanvas — PySide6 Graphics Editor", 760),
        ("ferrastra", "Ferrastra — oxidized image processing", 720),
    )
    for product, alt_text, width in products:
        readme = (_ROOT / f"packages/{product}/README.md").read_text("utf-8")
        base = (
            "https://raw.githubusercontent.com/Artificial-Sweetener/"
            f"CuteCanvas/main/assets/logos/{product}-logo"
        )
        assert readme.startswith('<h1 align="center">\n  <picture>')
        assert f'srcset="{base}-on-dark.svg"' in readme
        assert f'srcset="{base}-on-light.svg"' in readme
        assert f'src="{base}.svg"' in readme
        assert f'alt="{alt_text}"' in readme
        assert f'width="{width}"' in readme


def test_product_logo_variants_are_scalable_transparent_paths() -> None:
    """Keep every theme pair as matching responsive vector geometry."""
    for product, view_box in _PRODUCT_LOGOS:
        light_paths, light_style = _read_vector(product, "-on-light", view_box)
        dark_paths, dark_style = _read_vector(product, "-on-dark", view_box)
        adaptive_paths, adaptive_style = _read_vector(product, "", view_box)
        assert "#15161a" in light_style
        assert "#f5f5f7" in dark_style
        assert "#15161a" in adaptive_style
        assert "#f5f5f7" in adaptive_style
        assert "prefers-color-scheme: dark" in adaptive_style
        assert light_paths == dark_paths == adaptive_paths


def _read_vector(
    product: str,
    suffix: str,
    view_box: str,
) -> tuple[tuple[str, ...], str]:
    """Return validated path geometry and style for one logo asset."""
    logo = _ROOT / f"assets/logos/{product}-logo{suffix}.svg"
    root = ElementTree.parse(logo).getroot()
    assert root.attrib["viewBox"] == view_box
    assert "width" not in root.attrib
    assert "height" not in root.attrib
    assert root.find(f"{_SVG_NAMESPACE}image") is None
    style = root.find(f"{_SVG_NAMESPACE}style")
    assert style is not None
    paths = tuple(
        element.attrib["d"] for element in root.findall(f"{_SVG_NAMESPACE}path")
    )
    assert paths
    return paths, style.text or ""
