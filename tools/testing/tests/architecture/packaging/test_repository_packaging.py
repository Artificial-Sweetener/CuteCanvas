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
"""Verify repository-owned packaging and platform orchestration."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib

from tools.testing.policy import repository_root

_ROOT = repository_root()


def _metadata(path: Path) -> dict[str, Any]:
    """Load one repository-owned TOML policy with explicit value typing."""
    return tomllib.loads(path.read_text("utf-8"))


def test_repository_bootstrap_installs_all_editable_packages() -> None:
    """Keep the root setup path aligned with all three package roots."""
    development_requirements = (
        (_ROOT / "requirements-dev.txt").read_text("utf-8").splitlines()
    )
    root_requirements = (_ROOT / "requirements.txt").read_text("utf-8").splitlines()
    setup_source = (_ROOT / "tools/setup_dev.py").read_text("utf-8")

    assert "-e ./packages/qpane" in development_requirements
    assert "-e ./packages/cutecanvas" in development_requirements
    assert "-e ./packages/ferrastra" in development_requirements
    assert "-c constraints-tooling.txt" in development_requirements
    assert "-r requirements-dev.txt" in root_requirements
    assert 'repo_root / "constraints-tooling.txt"' in setup_source
    assert 'repo_root / "requirements-dev.txt"' in setup_source


def test_ferrastra_ci_and_dependency_policy_cover_minimum_native_targets() -> None:
    """Keep build, verification, and dependency graphs on the same platforms."""
    verify_workflow = (_ROOT / ".github/workflows/verify.yml").read_text("utf-8")
    release_workflow = (_ROOT / ".github/workflows/release.yml").read_text("utf-8")
    for runner in ("windows-2025", "ubuntu-24.04", "macos-15"):
        assert runner in verify_workflow
        assert runner in release_workflow

    deny_policy = _metadata(_ROOT / "deny.toml")
    assert deny_policy["graph"]["targets"] == [
        "x86_64-pc-windows-msvc",
        "x86_64-unknown-linux-gnu",
        "aarch64-apple-darwin",
    ]
    rust_toolchain = _metadata(_ROOT / "rust-toolchain.toml")
    assert "targets" not in rust_toolchain["toolchain"]
