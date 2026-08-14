#!/usr/bin/env python3
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
"""Reject Ferrastra release tags that disagree with the Cargo version."""

from __future__ import annotations

import argparse
from pathlib import Path

from tools.release.products import release_from_tag
from tools.release.pypi import release_exists

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib

_ROOT = Path(__file__).resolve().parents[1]
_CARGO_MANIFEST = _ROOT / "Cargo.toml"


def workspace_version(manifest: Path = _CARGO_MANIFEST) -> str:
    """Return the authoritative Ferrastra workspace package version."""
    metadata = tomllib.loads(manifest.read_text(encoding="utf-8"))
    return str(metadata["workspace"]["package"]["version"])


def release_tag_error(tag: str, version: str) -> str | None:
    """Return a mismatch error or ``None`` when the release tag is exact."""
    expected = f"ferrastra-v{version}"
    if tag == expected:
        return None
    return f"Ferrastra release tag must be {expected!r}, received {tag!r}"


def run(tag: str, *, check_pypi: bool = False) -> None:
    """Validate one Ferrastra release tag and optional index admission."""
    product, _release_version = release_from_tag(tag)
    if product.name != "ferrastra":
        raise ValueError(f"release tag must select Ferrastra, received {tag!r}")
    version = workspace_version()
    error = release_tag_error(tag, version)
    if error is not None:
        raise SystemExit(error)
    if check_pypi and release_exists("ferrastra", version):
        raise SystemExit(
            f"PyPI already contains immutable release ferrastra=={version}"
        )
    print(f"SUCCESS: {tag} matches Ferrastra workspace version {version}.")


def main() -> None:
    """Parse the release tag supplied by the publishing workflow."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="Git tag that triggered the Ferrastra release")
    parser.add_argument(
        "--check-pypi",
        action="store_true",
        help="reject an immutable Ferrastra version already present on PyPI",
    )
    arguments = parser.parse_args()
    try:
        run(arguments.tag, check_pypi=arguments.check_pypi)
    except (RuntimeError, ValueError) as error:
        parser.exit(1, f"ERROR: {error}\n")


if __name__ == "__main__":
    main()
