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
"""Own fail-closed PyPI admission checks for Python releases."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from .products import StableVersion, parse_stable_version

JsonLoader = Callable[[str], dict[str, Any]]


def load_pypi_json(url: str) -> dict[str, Any]:
    """Load one PyPI JSON response through a bounded network request."""
    try:
        with urlopen(url, timeout=20) as response:
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError(
            f"could not verify PyPI release state at {url}: {error}"
        ) from error
    if not isinstance(payload, dict):
        raise TypeError(f"PyPI returned a non-object response from {url}")
    return payload


def release_exists(
    package: str,
    version: str,
    *,
    loader: JsonLoader = load_pypi_json,
) -> bool:
    """Return whether PyPI already contains an immutable release version."""
    url = f"https://pypi.org/pypi/{package}/{version}/json"
    try:
        loader(url)
    except RuntimeError as error:
        cause = error.__cause__
        if isinstance(cause, HTTPError) and cause.code == 404:
            return False
        raise
    return True


def published_stable_versions(
    package: str,
    *,
    loader: JsonLoader = load_pypi_json,
) -> tuple[StableVersion, ...]:
    """Return every canonical stable version published for one project."""
    payload = loader(f"https://pypi.org/pypi/{package}/json")
    releases = payload.get("releases")
    if not isinstance(releases, dict):
        raise TypeError(f"PyPI metadata for {package!r} has no release mapping")
    stable: list[StableVersion] = []
    for value in releases:
        try:
            stable.append(parse_stable_version(str(value)))
        except ValueError:
            continue
    return tuple(sorted(stable))


def has_compatible_qpane_release(versions: tuple[StableVersion, ...]) -> bool:
    """Return whether PyPI contains a QPane release accepted by CuteCanvas 1.x."""
    return any((3, 0, 0) <= version < (4, 0, 0) for version in versions)
