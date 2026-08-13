#    QPane - High-performance PySide6 image viewer
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

"""Normalize typed scalar and sequence values accepted by QPane configuration."""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum
from typing import Any

from ..types import DiagnosticsDomain


def normalize_enum_value(value: Any, enum_cls: type[Enum], *, field: str) -> str:
    """Return the canonical enum value string or reject unsupported inputs."""
    if isinstance(value, enum_cls):
        return str(value.value)
    if isinstance(value, str):
        candidate = value.strip().lower()
        mapping = {member.value.lower(): member.value for member in enum_cls}
        if candidate in mapping:
            return mapping[candidate]
        raise ValueError(f"Unsupported {field} '{value}'")
    raise TypeError(f"{field} must be a string or {enum_cls.__name__}")


def normalize_domain_sequence(
    domains: Iterable[str | DiagnosticsDomain] | None,
) -> tuple[str, ...]:
    """Return canonical diagnostics domains deduplicated in order."""
    if domains is None:
        return ()
    if isinstance(domains, (str, DiagnosticsDomain)):
        domains = (domains,)
    normalized: list[str] = []
    seen: set[str] = set()
    for domain in domains:
        if isinstance(domain, Enum):
            canonical = str(domain.value).strip().lower()
        elif isinstance(domain, str):
            canonical = domain.strip().lower()
        else:
            raise TypeError("diagnostics domains must be strings or string enums")
        if not canonical:
            raise ValueError("diagnostics domains must be non-empty")
        if canonical not in seen:
            normalized.append(canonical)
            seen.add(canonical)
    return tuple(normalized)


__all__ = ["normalize_domain_sequence", "normalize_enum_value"]
