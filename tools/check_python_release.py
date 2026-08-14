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
"""Validate a QPane or CuteCanvas tag before release artifacts are built."""

from __future__ import annotations

import argparse

from tools.release.candidate import read_product_requirements
from tools.release.products import format_version, python_release_from_tag
from tools.release.pypi import (
    has_compatible_release,
    published_stable_versions,
    release_exists,
)


def run(tag: str, *, check_pypi: bool) -> None:
    """Validate one product tag and optional public-index admission."""
    product, version = python_release_from_tag(tag)
    version_text = format_version(version)
    if check_pypi and release_exists(product.name, version_text):
        raise RuntimeError(
            f"PyPI already contains immutable release {product.name}=={version_text}"
        )
    if check_pypi:
        requirements = read_product_requirements(
            product.package_path / "pyproject.toml"
        )
        for dependency in product.dependencies:
            published = published_stable_versions(dependency.name)
            specifier = requirements[dependency.name]
            if not has_compatible_release(published, specifier):
                raise RuntimeError(
                    f"{product.display_name} requires a published "
                    f"{dependency.name}{specifier} release; publish a compatible "
                    f"{dependency.name} before {product.name}"
                )
    print(f"SUCCESS: {tag} admits {product.name}=={version_text} for artifact build.")


def main() -> None:
    """Parse the release tag supplied by publishing CI."""
    parser = argparse.ArgumentParser()
    parser.add_argument("tag", help="Product-prefixed Git release tag")
    parser.add_argument(
        "--check-pypi",
        action="store_true",
        help="reject existing versions and unavailable public dependencies",
    )
    arguments = parser.parse_args()
    try:
        run(arguments.tag, check_pypi=arguments.check_pypi)
    except (RuntimeError, ValueError) as error:
        parser.exit(1, f"ERROR: {error}\n")


if __name__ == "__main__":
    main()
