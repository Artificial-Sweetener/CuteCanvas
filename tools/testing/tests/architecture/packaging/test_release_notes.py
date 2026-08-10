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
"""Prove package-scoped changelog selection and presentation."""

from __future__ import annotations

import subprocess
from pathlib import Path

from tools.release.notes import generate_release_notes, previous_release_tag
from tools.release.products import PRODUCTS


def test_release_notes_include_only_user_facing_changes_for_the_product(
    tmp_path: Path,
) -> None:
    """Exclude sibling-package and internal-only commits from QPane notes."""
    _initialize_repository(tmp_path)
    _commit(tmp_path, "packages/qpane/base.py", "base", "feat(qpane): ship viewer")
    _git(tmp_path, "tag", "v2.1.1")
    _commit(
        tmp_path,
        "packages/cutecanvas/editor.py",
        "editor",
        "feat(cutecanvas): add editor",
    )
    _commit(tmp_path, "packages/qpane/fix.py", "fix", "fix(qpane): repair frames")
    _commit(tmp_path, "packages/qpane/test.py", "test", "test(qpane): add proof")

    product = PRODUCTS["qpane"]
    assert previous_release_tag(tmp_path, product, "qpane-v3.0.0") == "v2.1.1"
    notes = generate_release_notes(tmp_path, product, (3, 0, 0), "qpane-v3.0.0")

    assert "repair frames" in notes
    assert "add editor" not in notes
    assert "add proof" not in notes
    assert "v2.1.1...qpane-v3.0.0" in notes


def test_ferrastra_release_notes_include_native_workspace_changes(
    tmp_path: Path,
) -> None:
    """Include crate changes while excluding sibling package features."""
    _initialize_repository(tmp_path)
    _commit(
        tmp_path,
        "packages/ferrastra/src/ferrastra/__init__.py",
        "base",
        "feat(ferrastra): establish native package",
    )
    _git(tmp_path, "tag", "ferrastra-v0.1.0")
    _commit(
        tmp_path,
        "crates/ferrastra-core/src/lib.rs",
        "native",
        "feat(ferrastra): add graph products",
    )
    _commit(
        tmp_path,
        "packages/qpane/src/qpane/viewer.py",
        "viewer",
        "feat(qpane): add viewer workflow",
    )

    product = PRODUCTS["ferrastra"]
    notes = generate_release_notes(
        tmp_path,
        product,
        (0, 2, 0),
        "ferrastra-v0.2.0",
    )

    assert "add graph products" in notes
    assert "add viewer workflow" not in notes


def test_first_product_release_notes_are_presented_as_initial_release(
    tmp_path: Path,
) -> None:
    """Avoid presenting pre-lineage implementation history as release notes."""
    _initialize_repository(tmp_path)
    _commit(
        tmp_path,
        "packages/cutecanvas/src/cutecanvas/editor.py",
        "editor",
        "feat(cutecanvas): add editor",
    )

    notes = generate_release_notes(
        tmp_path,
        PRODUCTS["cutecanvas"],
        (1, 0, 0),
        "cutecanvas-v1.0.0",
    )

    assert notes == "# CuteCanvas 1.0.0\n\nInitial release.\n"


def _initialize_repository(root: Path) -> None:
    """Create an isolated Git history for release-note selection."""
    _git(root, "init")
    _git(root, "config", "user.name", "Release Test")
    _git(root, "config", "user.email", "release@example.invalid")


def _commit(root: Path, relative: str, content: str, subject: str) -> None:
    """Commit one path and subject in the isolated repository."""
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _git(root, "add", "--", relative)
    _git(root, "commit", "-m", subject)


def _git(root: Path, *arguments: str) -> None:
    """Run one checked Git command without interactive configuration."""
    subprocess.run(
        ("git", *arguments),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
