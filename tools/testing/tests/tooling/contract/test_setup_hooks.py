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
"""Protect generated Git hooks from mutating work or expanding commit scope."""

from __future__ import annotations

import subprocess
from pathlib import Path

from tools import setup_hooks


def test_pre_commit_hook_is_check_only(tmp_path: Path, monkeypatch) -> None:
    """Generated hooks must never rewrite or stage repository files."""
    hook_dir = tmp_path / ".git" / "hooks"
    hook_dir.mkdir(parents=True)
    monkeypatch.setattr(setup_hooks, "_git_root", lambda: tmp_path)
    monkeypatch.setattr(
        setup_hooks,
        "_ensure_hook_directory",
        lambda _git_root: hook_dir,
    )

    assert setup_hooks.main() == 0

    hook = (tmp_path / ".git/hooks/pre-commit").read_text(encoding="utf-8")
    assert "ruff check --fix" not in hook
    assert "git add" not in hook
    assert "-m black --check ." in hook
    assert "fix_encoding.py --check" in hook
    assert "check_docstrings.py --check" in hook
    assert "add_license_headers.py --check" in hook
    assert "check_architecture.py --staged" in hook
    assert "check_ferrastra_architecture.py" not in hook


def test_pre_commit_hook_isolates_tests_from_commit_git_state(
    tmp_path: Path, monkeypatch
) -> None:
    """Keep nested test repositories independent from the committing worktree."""
    hook_dir = tmp_path / ".git" / "hooks"
    hook_dir.mkdir(parents=True)
    monkeypatch.setattr(setup_hooks, "_git_root", lambda: tmp_path)
    monkeypatch.setattr(
        setup_hooks,
        "_ensure_hook_directory",
        lambda _git_root: hook_dir,
    )

    assert setup_hooks.main() == 0

    hook = (tmp_path / ".git/hooks/pre-commit").read_text(encoding="utf-8")
    assert "git rev-parse --local-env-vars" in hook
    assert 'unset "$GIT_VARIABLE"' in hook
    assert '"$PYTHON" tools/test.py ci' in hook
    assert "pytest -n auto" not in hook
    assert "--path-format=absolute --git-path hooks" in hook


def test_hook_directory_resolves_linked_worktree_git_path(
    tmp_path: Path, monkeypatch
) -> None:
    """Install hooks through Git instead of assuming that .git is a directory."""
    expected = tmp_path / "common" / "hooks"

    def resolve_git_path(*args, **kwargs):
        """Return the common hook path for the simulated linked worktree."""
        assert args[0] == [
            "git",
            "rev-parse",
            "--path-format=absolute",
            "--git-path",
            "hooks",
        ]
        assert kwargs["cwd"] == tmp_path
        return subprocess.CompletedProcess(args[0], 0, f"{expected}\n", "")

    monkeypatch.setattr(setup_hooks.subprocess, "run", resolve_git_path)

    assert setup_hooks._ensure_hook_directory(tmp_path) == expected
    assert expected.is_dir()
