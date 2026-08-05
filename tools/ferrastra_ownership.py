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
"""Enforce migration-stage canonical numerical ownership."""

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

try:
    from tools.architecture.model import Diagnostic
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from architecture.model import Diagnostic


@dataclass(frozen=True, slots=True)
class ForbiddenPattern:
    """Describe one legacy implementation pattern banned after migration."""

    path: str
    pattern: str


@dataclass(frozen=True, slots=True)
class OwnershipAllowance:
    """Describe one accountable temporary presentation exception."""

    path: str
    pattern: str
    owner: str
    reason: str
    issue: str
    expires: date


@dataclass(frozen=True, slots=True)
class MigrationPolicy:
    """Describe one numerical responsibility and its migration state."""

    identifier: str
    status: str
    owner: str
    activation_phase: str
    forbidden: tuple[ForbiddenPattern, ...]
    allowances: tuple[OwnershipAllowance, ...]


def validate_ownership(
    root: Path,
    *,
    config_path: Path | None = None,
    today: date | None = None,
) -> list[Diagnostic]:
    """Return canonical ownership and allowance diagnostics."""
    path = config_path or root / "FERRASTRA_OWNERSHIP.toml"
    try:
        migrations = _load_migrations(path)
    except (OSError, TypeError, ValueError) as exc:
        return [Diagnostic("OWN001", path.name, str(exc))]
    current_date = today or datetime.now(timezone.utc).date()
    diagnostics: list[Diagnostic] = []
    for migration in migrations:
        diagnostics.extend(
            _allowance_lifecycle_diagnostics(path, migration, current_date)
        )
        if migration.status == "migrated":
            diagnostics.extend(_validate_migrated_owner(root, migration, current_date))
    return sorted(
        diagnostics,
        key=lambda item: (item.path, item.line, item.rule, item.message),
    )


def _load_migrations(path: Path) -> tuple[MigrationPolicy, ...]:
    """Load the schema-versioned canonical ownership manifest."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("schema_version must be 1")
    raw_migrations = data.get("migrations")
    if not isinstance(raw_migrations, list) or not raw_migrations:
        raise ValueError("migrations must be a nonempty array")
    migration_items = cast(list[object], raw_migrations)
    migrations = tuple(
        _parse_migration(cast(dict[str, Any], item), index)
        for index, item in enumerate(migration_items)
        if isinstance(item, dict)
    )
    if len(migrations) != len(migration_items):
        raise ValueError("every migration must be a table")
    identifiers = [migration.identifier for migration in migrations]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("migration ids must be unique")
    return migrations


def _parse_migration(data: dict[str, Any], index: int) -> MigrationPolicy:
    """Parse one complete migration policy."""
    identifier = _required_string(data, "id", f"migration {index}")
    status = _required_string(data, "status", identifier)
    if status not in {"planned", "migrated"}:
        raise ValueError(f"{identifier} status must be planned or migrated")
    forbidden = _pattern_tables(data.get("forbidden"), identifier)
    allowances = _allowance_tables(data.get("allowances", []), identifier)
    return MigrationPolicy(
        identifier=identifier,
        status=status,
        owner=_required_string(data, "owner", identifier),
        activation_phase=_required_string(data, "activation_phase", identifier),
        forbidden=forbidden,
        allowances=allowances,
    )


def _pattern_tables(value: object, owner: str) -> tuple[ForbiddenPattern, ...]:
    """Parse one nonempty forbidden-pattern array."""
    if not isinstance(value, list) or not value:
        raise ValueError(f"{owner} requires forbidden patterns")
    patterns: list[ForbiddenPattern] = []
    for index, raw in enumerate(cast(list[object], value)):
        if not isinstance(raw, dict):
            raise TypeError(f"{owner} forbidden entry {index} must be a table")
        item = cast(dict[str, Any], raw)
        patterns.append(
            ForbiddenPattern(
                path=_required_string(item, "path", owner),
                pattern=_required_string(item, "pattern", owner),
            )
        )
    return tuple(patterns)


def _allowance_tables(value: object, owner: str) -> tuple[OwnershipAllowance, ...]:
    """Parse presentation allowances with complete accountability metadata."""
    if not isinstance(value, list):
        raise TypeError(f"{owner} allowances must be an array")
    allowances: list[OwnershipAllowance] = []
    for index, raw in enumerate(cast(list[object], value)):
        if not isinstance(raw, dict):
            raise TypeError(f"{owner} allowance {index} must be a table")
        item = cast(dict[str, Any], raw)
        expires_value = item.get("expires")
        if isinstance(expires_value, date):
            expires = expires_value
        elif isinstance(expires_value, str):
            expires = date.fromisoformat(expires_value)
        else:
            raise TypeError(f"{owner} allowance {index} requires an ISO expiry date")
        allowances.append(
            OwnershipAllowance(
                path=_required_string(item, "path", owner),
                pattern=_required_string(item, "pattern", owner),
                owner=_required_string(item, "owner", owner),
                reason=_required_string(item, "reason", owner),
                issue=_required_string(item, "issue", owner),
                expires=expires,
            )
        )
    return tuple(allowances)


def _validate_migrated_owner(
    root: Path,
    migration: MigrationPolicy,
    current_date: date,
) -> list[Diagnostic]:
    """Reject legacy numerical patterns for one completed migration."""
    diagnostics: list[Diagnostic] = []
    matched_allowances: set[OwnershipAllowance] = set()
    for forbidden in migration.forbidden:
        for path in _matching_files(root, forbidden.path):
            source = path.read_text(encoding="utf-8")
            offset = 0
            while True:
                index = source.find(forbidden.pattern, offset)
                if index < 0:
                    break
                relative_path = path.relative_to(root).as_posix()
                allowance = next(
                    (
                        item
                        for item in migration.allowances
                        if item.expires >= current_date
                        and item.pattern == forbidden.pattern
                        and fnmatch.fnmatchcase(relative_path, item.path)
                    ),
                    None,
                )
                if allowance is None:
                    diagnostics.append(
                        Diagnostic(
                            "OWN002",
                            relative_path,
                            f"{migration.identifier} is owned by {migration.owner}; "
                            f"legacy pattern is forbidden: {forbidden.pattern}",
                            source.count("\n", 0, index) + 1,
                        )
                    )
                else:
                    matched_allowances.add(allowance)
                offset = index + len(forbidden.pattern)
    diagnostics.extend(
        Diagnostic(
            "OWN003",
            "FERRASTRA_OWNERSHIP.toml",
            f"unused allowance for {migration.identifier}: {allowance.path}",
        )
        for allowance in migration.allowances
        if allowance.expires >= current_date and allowance not in matched_allowances
    )
    return diagnostics


def _matching_files(root: Path, pattern: str) -> tuple[Path, ...]:
    """Return files for a repository glob, including directory-wide ``/**`` globs."""
    file_pattern = f"{pattern}/*" if pattern.endswith("/**") else pattern
    return tuple(path for path in sorted(root.glob(file_pattern)) if path.is_file())


def _allowance_lifecycle_diagnostics(
    path: Path,
    migration: MigrationPolicy,
    current_date: date,
) -> list[Diagnostic]:
    """Reject expired ownership exceptions independently of migration state."""
    return [
        Diagnostic(
            "OWN004",
            path.name,
            f"{migration.identifier} allowance expired on {allowance.expires.isoformat()}",
        )
        for allowance in migration.allowances
        if allowance.expires < current_date
    ]


def _required_string(data: dict[str, Any], key: str, owner: str) -> str:
    """Return one required nonempty string."""
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{owner} requires nonempty {key}")
    return value
