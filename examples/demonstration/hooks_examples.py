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

"""Load editable extension example scripts for the demonstration UI."""

from __future__ import annotations

from pathlib import Path

_EXAMPLE_DIR = Path(__file__).resolve().parent / "extension_examples"


def execute_trusted_extension(
    code: str,
    namespace: dict[str, object],
    *,
    source_name: str,
) -> None:
    """Execute code entered in the demo's explicit local extension editor."""
    compiled = compile(code, source_name, "exec")
    exec(compiled, namespace)  # noqa: S102 - deliberate trusted-code boundary


def load_custom_cursor_example() -> tuple[str, str | None]:
    """Load the cursor-provider example from disk."""
    return _load_extension_example("custom_cursor.py")


def load_custom_overlay_example() -> tuple[str, str | None]:
    """Load the overlay example from disk."""
    return _load_extension_example("custom_overlay.py")


def load_lens_example() -> tuple[str, str | None]:
    """Load the combined cursor/overlay lens example from disk."""
    return _load_extension_example("lens_tool.py")


def _load_extension_example(filename: str) -> tuple[str, str | None]:
    """Return the example script contents and any load error."""
    path = _EXAMPLE_DIR / filename
    try:
        return path.read_text(encoding="utf-8"), None
    except (OSError, UnicodeError) as exc:
        message = f"Failed to load extension example: {path} ({exc})"
        return "", message
