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
"""Characterize the versioned Ferrastra benchmark policy."""

from __future__ import annotations

from pathlib import Path

from tools.check_ferrastra_benchmarks import validate_manifest
from tools.testing.policy import repository_root

_ROOT = repository_root()


def test_repository_benchmark_manifest_is_complete() -> None:
    """Keep the checked-in Stage 0 measurement contract valid."""
    assert validate_manifest() == []


def test_manifest_rejects_missing_tail_latency(tmp_path: Path) -> None:
    """Keep p99 latency mandatory for every future operation benchmark."""
    source = (_ROOT / "benchmarks/ferrastra_manifest.toml").read_text(encoding="utf-8")
    manifest = tmp_path / "manifest.toml"
    manifest.write_text(source.replace("[50, 95, 99]", "[50, 95]"), encoding="utf-8")

    assert "measurement.percentiles must be [50, 95, 99]" in validate_manifest(manifest)
