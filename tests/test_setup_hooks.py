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

from pathlib import Path

from tools import setup_hooks


def test_pre_commit_hook_is_check_only(tmp_path: Path, monkeypatch) -> None:
    """Generated hooks must never rewrite or stage repository files."""
    monkeypatch.setattr(setup_hooks, "_git_root", lambda: tmp_path)

    assert setup_hooks.main() == 0

    hook = (tmp_path / ".git/hooks/pre-commit").read_text(encoding="utf-8")
    assert "ruff check --fix" not in hook
    assert "git add" not in hook
    assert "-m black --check ." in hook
    assert "fix_encoding.py --check" in hook
    assert "check_docstrings.py --check" in hook
    assert "add_license_headers.py --check" in hook
