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
"""Own the three products' independent release identities and tag contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .compatibility import STABLE_MAJOR_PRERELEASE_MINOR, CompatibilityPolicy

StableVersion = tuple[int, int, int]

_STABLE_VERSION = re.compile(
    r"^(?P<major>0|[1-9][0-9]*)\."
    r"(?P<minor>0|[1-9][0-9]*)\."
    r"(?P<patch>0|[1-9][0-9]*)$"
)


@dataclass(frozen=True)
class ReleaseDependency:
    """Describe one version-derived dependency edge between products."""

    name: str
    policy: CompatibilityPolicy


@dataclass(frozen=True)
class ReleaseProduct:
    """Describe one independently versioned and published product."""

    name: str
    display_name: str
    package_path: Path
    first_release: StableVersion
    additional_release_paths: tuple[Path, ...] = ()
    legacy_tag_fallback: bool = False
    wheel_platforms: tuple[str, ...] = ()
    dependencies: tuple[ReleaseDependency, ...] = ()

    @property
    def tag_prefix(self) -> str:
        """Return the product-specific Git tag prefix."""
        return f"{self.name}-v"

    @property
    def release_paths(self) -> tuple[Path, ...]:
        """Return every repository path owned by the product's release history."""
        return (self.package_path, *self.additional_release_paths)


PRODUCTS = {
    "ferrastra": ReleaseProduct(
        name="ferrastra",
        display_name="Ferrastra",
        package_path=Path("packages/ferrastra"),
        first_release=(1, 0, 0),
        additional_release_paths=(
            Path("crates"),
            Path("Cargo.toml"),
            Path("Cargo.lock"),
            Path("rust-toolchain.toml"),
        ),
        wheel_platforms=("linux-x64", "windows-x64", "macos-arm64"),
    ),
    "qpane": ReleaseProduct(
        name="qpane",
        display_name="QPane",
        package_path=Path("packages/qpane"),
        first_release=(3, 0, 0),
        legacy_tag_fallback=True,
        dependencies=(ReleaseDependency("ferrastra", STABLE_MAJOR_PRERELEASE_MINOR),),
    ),
    "cutecanvas": ReleaseProduct(
        name="cutecanvas",
        display_name="CuteCanvas",
        package_path=Path("packages/cutecanvas"),
        first_release=(1, 0, 0),
        dependencies=(
            ReleaseDependency("ferrastra", STABLE_MAJOR_PRERELEASE_MINOR),
            ReleaseDependency("qpane", STABLE_MAJOR_PRERELEASE_MINOR),
        ),
    ),
}
PYTHON_PRODUCTS = {name: PRODUCTS[name] for name in ("qpane", "cutecanvas")}


def parse_stable_version(value: str) -> StableVersion:
    """Parse an exact stable semantic version.

    Raises:
        ValueError: If ``value`` is not canonical ``MAJOR.MINOR.PATCH``.
    """
    match = _STABLE_VERSION.fullmatch(value)
    if match is None:
        raise ValueError(
            f"release version must be stable MAJOR.MINOR.PATCH, received {value!r}"
        )
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
    )


def format_version(version: StableVersion) -> str:
    """Return a canonical stable semantic version string."""
    return ".".join(str(part) for part in version)


def release_from_tag(tag: str) -> tuple[ReleaseProduct, StableVersion]:
    """Resolve an exact product-prefixed release tag.

    Raises:
        ValueError: If the product or version is unsupported.
    """
    product = next(
        (
            candidate
            for candidate in PRODUCTS.values()
            if tag.startswith(candidate.tag_prefix)
        ),
        None,
    )
    if product is None:
        expected = ", ".join(f"{item.tag_prefix}X.Y.Z" for item in PRODUCTS.values())
        raise ValueError(f"release tag must match one of {expected}; received {tag!r}")
    version = parse_stable_version(tag.removeprefix(product.tag_prefix))
    if version < product.first_release:
        raise ValueError(
            f"{product.display_name} release tags begin at "
            f"{format_version(product.first_release)}; received {format_version(version)}"
        )
    return product, version


def python_release_from_tag(tag: str) -> tuple[ReleaseProduct, StableVersion]:
    """Resolve a release tag admitted by Python-only artifact checks.

    Raises:
        ValueError: If the tag selects Ferrastra or is otherwise invalid.
    """
    product, version = release_from_tag(tag)
    if product.name not in PYTHON_PRODUCTS:
        expected = ", ".join(
            f"{item.tag_prefix}X.Y.Z" for item in PYTHON_PRODUCTS.values()
        )
        raise ValueError(
            f"Python release tag must match one of {expected}; received {tag!r}"
        )
    return product, version
