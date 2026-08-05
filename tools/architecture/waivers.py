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
"""Apply accountable, expiring architecture waivers."""

from __future__ import annotations

import fnmatch
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, cast

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10 only
    import tomli as tomllib

from .model import Diagnostic


@dataclass(frozen=True, slots=True)
class _Waiver:
    """Represent one validated architecture exception."""

    identifier: str
    rule: str
    path: str
    owner: str
    reason: str
    issue: str
    expires: date


def apply_waivers(
    diagnostics: list[Diagnostic],
    waiver_path: Path,
    *,
    today: date | None = None,
) -> list[Diagnostic]:
    """Suppress exact active exceptions and reject stale waiver entries."""
    current_date = today or datetime.now(timezone.utc).date()
    waivers, waiver_diagnostics = _load_waivers(waiver_path)
    if waiver_diagnostics:
        return [*diagnostics, *waiver_diagnostics]
    active = [waiver for waiver in waivers if waiver.expires >= current_date]
    expired = [waiver for waiver in waivers if waiver.expires < current_date]
    results = [
        Diagnostic(
            "WAIVER001",
            waiver_path.name,
            f"waiver {waiver.identifier} expired on {waiver.expires.isoformat()}",
        )
        for waiver in expired
    ]
    matched: set[str] = set()
    for diagnostic in diagnostics:
        waiver = next(
            (
                item
                for item in active
                if item.rule == diagnostic.rule
                and fnmatch.fnmatchcase(diagnostic.path, item.path)
            ),
            None,
        )
        if waiver is None:
            results.append(diagnostic)
        else:
            matched.add(waiver.identifier)
    results.extend(
        Diagnostic(
            "WAIVER002",
            waiver_path.name,
            f"active waiver {waiver.identifier} matches no diagnostic",
        )
        for waiver in active
        if waiver.identifier not in matched
    )
    return results


def _load_waivers(path: Path) -> tuple[tuple[_Waiver, ...], list[Diagnostic]]:
    """Load waiver records and return schema diagnostics instead of exceptions."""
    try:
        return _parse_waivers(path), []
    except (OSError, ValueError, TypeError) as exc:
        return (), [Diagnostic("WAIVER003", path.name, str(exc))]


def _parse_waivers(path: Path) -> tuple[_Waiver, ...]:
    """Parse and validate the complete waiver document."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("schema_version must be 1")
    raw_waivers = data.get("waivers", [])
    if not isinstance(raw_waivers, list):
        raise TypeError("waivers must be an array")
    waiver_items = cast(list[object], raw_waivers)
    waivers = tuple(
        _parse_waiver(cast(dict[str, Any], raw), index)
        for index, raw in enumerate(waiver_items)
        if isinstance(raw, dict)
    )
    if len(waivers) != len(waiver_items):
        raise ValueError("every waiver must be a table")
    identifiers = [waiver.identifier for waiver in waivers]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("waiver ids must be unique")
    return waivers


def _parse_waiver(data: dict[str, Any], index: int) -> _Waiver:
    """Parse one complete waiver table."""
    identifier = _required_string(data, "id", index)
    expires_value = data.get("expires")
    if isinstance(expires_value, date):
        expires = expires_value
    elif isinstance(expires_value, str):
        expires = date.fromisoformat(expires_value)
    else:
        raise TypeError(f"waiver {identifier} expires must be an ISO date")
    return _Waiver(
        identifier=identifier,
        rule=_required_string(data, "rule", index),
        path=_required_string(data, "path", index),
        owner=_required_string(data, "owner", index),
        reason=_required_string(data, "reason", index),
        issue=_required_string(data, "issue", index),
        expires=expires,
    )


def _required_string(data: dict[str, Any], key: str, index: int) -> str:
    """Return one required waiver string."""
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"waiver {index} requires nonempty {key}")
    return value
