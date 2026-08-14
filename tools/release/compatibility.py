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
"""Own version-range policy for dependencies between released products."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from packaging.specifiers import SpecifierSet
from packaging.version import Version

StableVersion = tuple[int, int, int]


class UpperBoundPolicy(str, Enum):
    """Select the exclusive compatibility boundary for a dependency edge."""

    NEXT_MAJOR = "next-major"
    NEXT_MINOR = "next-minor"


@dataclass(frozen=True)
class CompatibilityPolicy:
    """Derive one canonical range from an exact released dependency version."""

    stable_upper_bound: UpperBoundPolicy
    zero_upper_bound: UpperBoundPolicy

    def specifier(self, version: StableVersion) -> str:
        """Return the canonical range accepting ``version`` as its minimum."""
        upper_policy = (
            self.zero_upper_bound if version[0] == 0 else self.stable_upper_bound
        )
        upper = _upper_bound(version, upper_policy)
        return f">={_format_version(version)},<{_format_version(upper)}"

    def accepts(self, specifier: str, version: StableVersion) -> bool:
        """Return whether ``specifier`` admits the exact dependency version."""
        candidate = Version(_format_version(version))
        return candidate in SpecifierSet(specifier)


STABLE_MAJOR_PRERELEASE_MINOR = CompatibilityPolicy(
    stable_upper_bound=UpperBoundPolicy.NEXT_MAJOR,
    zero_upper_bound=UpperBoundPolicy.NEXT_MINOR,
)


def _upper_bound(
    version: StableVersion,
    policy: UpperBoundPolicy,
) -> StableVersion:
    """Return the exclusive upper bound selected by ``policy``."""
    major, minor, _patch = version
    if policy is UpperBoundPolicy.NEXT_MAJOR:
        return (major + 1, 0, 0)
    return (major, minor + 1, 0)


def _format_version(version: StableVersion) -> str:
    """Return a canonical stable semantic version."""
    return ".".join(str(part) for part in version)
