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
"""Characterize canonical numerical ownership migration enforcement."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from tools.ferrastra_ownership import validate_ownership


def _write(path: Path, source: str) -> None:
    """Write one UTF-8 fixture after creating its parent directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _manifest(status: str, *, allowance: str = "") -> str:
    """Return one ownership manifest with an optional allowance table."""
    return (
        "schema_version = 1\n"
        "[[migrations]]\n"
        'id = "canonical-scale"\n'
        f'status = "{status}"\n'
        'owner = "ferrastra-raster"\n'
        'activation_phase = "Phase 2"\n'
        'forbidden = [{ path = "python/**", pattern = "legacy_scale" }]\n'
        f"{allowance}"
    )


def test_planned_migration_records_policy_without_rejecting_legacy_code(
    tmp_path: Path,
) -> None:
    """Planned ownership does not activate its legacy implementation ban early."""
    config = tmp_path / "FERRASTRA_OWNERSHIP.toml"
    _write(config, _manifest("planned"))
    _write(tmp_path / "python/legacy.py", "legacy_scale()\n")

    assert validate_ownership(tmp_path, config_path=config) == []


def test_migrated_ownership_rejects_legacy_implementation(tmp_path: Path) -> None:
    """A completed migration makes duplicate numerical ownership a hard error."""
    config = tmp_path / "FERRASTRA_OWNERSHIP.toml"
    _write(config, _manifest("migrated"))
    _write(tmp_path / "python/legacy.py", "legacy_scale()\n")

    assert {item.rule for item in validate_ownership(tmp_path, config_path=config)} == {
        "OWN002"
    }


def test_accountable_allowances_must_be_active_and_used(tmp_path: Path) -> None:
    """Ownership exceptions suppress exact uses and reject stale or unused entries."""
    config = tmp_path / "FERRASTRA_OWNERSHIP.toml"
    active = (
        '[[migrations.allowances]]\npath = "python/legacy.py"\n'
        'pattern = "legacy_scale"\nowner = "rendering-team"\n'
        'reason = "presentation conversion"\nissue = "FERRASTRA-2"\n'
        "expires = 2030-01-01\n"
    )
    _write(config, _manifest("migrated", allowance=active))
    _write(tmp_path / "python/legacy.py", "legacy_scale()\n")

    assert (
        validate_ownership(
            tmp_path,
            config_path=config,
            today=date(2029, 1, 1),
        )
        == []
    )
    (tmp_path / "python/legacy.py").write_text("clean()\n", encoding="utf-8")
    assert {
        item.rule
        for item in validate_ownership(
            tmp_path,
            config_path=config,
            today=date(2029, 1, 1),
        )
    } == {"OWN003"}
    assert {
        item.rule
        for item in validate_ownership(
            tmp_path,
            config_path=config,
            today=date(2031, 1, 1),
        )
    } == {"OWN004"}
