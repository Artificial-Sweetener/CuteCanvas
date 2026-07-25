#!/usr/bin/env python3
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
"""Launch the complete QPane viewer tutorial.

The example keeps application chrome in focused modules under
:mod:`examples.qpane_demonstration` while every image, scene, navigation, and
extension operation goes through QPane's public viewer and rendering facade.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if __package__ is None or __package__ == "":
    _REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(_REPOSITORY_ROOT))
    sys.path.insert(0, str(_REPOSITORY_ROOT / "packages" / "qpane" / "src"))

from examples.demo_environment import (
    DemoEnvironmentError,
    DemoEnvironmentManager,
    DemoLaunchSettings,
)

if TYPE_CHECKING:
    from examples.qpane_demonstration import ViewerWindow

__all__ = ["ViewerWindow", "main"]
_DEMO_ENVIRONMENTS = DemoEnvironmentManager(Path(__file__))


def _load_viewer_window() -> Any:
    """Import and cache the GUI window only after environment handoff."""
    window_type = globals().get("ViewerWindow")
    if window_type is None:
        from examples.qpane_demonstration import ViewerWindow as DemoViewerWindow

        globals()["ViewerWindow"] = DemoViewerWindow
        window_type = DemoViewerWindow
    return window_type


def __getattr__(name: str) -> Any:
    """Lazily expose the demo window for tests and host examples."""
    if name != "ViewerWindow":
        raise AttributeError(name)
    return _load_viewer_window()


def main(argv: Iterable[str] | None = None) -> int:
    """Provision when necessary and launch the QPane viewer example."""
    args = list(argv) if argv is not None else sys.argv[1:]
    skip_bootstrap = "--skip-bootstrap" in args
    if not skip_bootstrap and not _DEMO_ENVIRONMENTS.is_current_process("qpane"):
        try:
            _DEMO_ENVIRONMENTS.ensure_ready("qpane")
        except (DemoEnvironmentError, OSError, subprocess.CalledProcessError) as exc:
            print(f"\nError: {exc}")
            return 1
        return _DEMO_ENVIRONMENTS.launch("qpane", DemoLaunchSettings())
    from PySide6.QtWidgets import QApplication

    window_type = _load_viewer_window()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("QPane Demo")
    window = window_type()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
