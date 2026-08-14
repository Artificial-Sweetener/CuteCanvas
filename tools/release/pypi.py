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
from enum import Enum
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from packaging.specifiers import SpecifierSet
from packaging.version import Version

from .products import StableVersion, parse_stable_version

JsonLoader = Callable[[str], dict[str, Any]]


class PublicationState(str, Enum):
    """Describe how much of one planned immutable release exists on PyPI."""

    ABSENT = "absent"
    PARTIAL = "partial"
    COMPLETE = "complete"


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
        version = _stable_version_or_none(str(value))
        if version is not None:
            stable.append(version)
    return tuple(sorted(stable))


def _stable_version_or_none(value: str) -> StableVersion | None:
    """Parse a stable version while ignoring prerelease and legacy labels."""
    try:
        return parse_stable_version(value)
    except ValueError:
        return None


def has_compatible_release(
    versions: tuple[StableVersion, ...],
    specifier: str,
) -> bool:
    """Return whether any published stable version satisfies a dependency line."""
    accepted = SpecifierSet(specifier)
    return any(
        Version(".".join(str(part) for part in version)) in accepted
        for version in versions
    )


def planned_publication_state(
    package: str,
    version: str,
    expected_hashes: dict[str, str],
    *,
    loader: JsonLoader = load_pypi_json,
) -> PublicationState:
    """Return exact PyPI state or reject foreign files and hash mismatches."""
    url = f"https://pypi.org/pypi/{package}/{version}/json"
    try:
        payload = loader(url)
    except RuntimeError as error:
        cause = error.__cause__
        if isinstance(cause, HTTPError) and cause.code == 404:
            return PublicationState.ABSENT
        raise
    urls = payload.get("urls")
    if not isinstance(urls, list):
        raise TypeError(f"PyPI metadata for {package}=={version} has no URL list")
    actual: dict[str, str] = {}
    for value in urls:
        if not isinstance(value, dict):
            raise TypeError(f"PyPI file metadata for {package}=={version} is invalid")
        filename = str(value.get("filename", ""))
        digests = value.get("digests")
        sha256 = str(digests.get("sha256", "")) if isinstance(digests, dict) else ""
        if not filename or not sha256 or filename in actual:
            raise RuntimeError(
                f"PyPI file metadata for {package}=={version} is ambiguous"
            )
        actual[filename] = sha256
    unexpected = set(actual) - set(expected_hashes)
    if unexpected:
        raise RuntimeError(
            f"PyPI contains foreign files for {package}=={version}: {sorted(unexpected)}"
        )
    mismatched = [
        filename
        for filename, digest in actual.items()
        if expected_hashes[filename] != digest
    ]
    if mismatched:
        raise RuntimeError(
            f"PyPI hashes disagree with the release plan for {package}=={version}: "
            f"{sorted(mismatched)}"
        )
    if not actual:
        return PublicationState.ABSENT
    if set(actual) == set(expected_hashes):
        return PublicationState.COMPLETE
    return PublicationState.PARTIAL
