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

"""Bootstrap the local development environment for QPane."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PIP_VERSION = "26.1.2"


def _venv_python(venv_dir: Path) -> Path:
    """Return the venv Python executable path for the current platform."""
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _create_venv(venv_dir: Path) -> None:
    """Create the development virtual environment when missing."""
    if venv_dir.exists():
        return
    subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)


def _install_requirements(python_path: Path, requirements_path: Path) -> None:
    """Install the development dependencies into the virtual environment."""
    subprocess.run(
        [str(python_path), "-m", "pip", "install", "-r", str(requirements_path)],
        check=True,
    )


def _install_pinned_pip(python_path: Path) -> None:
    """Install the repository's pinned package installer version."""
    subprocess.run(
        [
            str(python_path),
            "-m",
            "pip",
            "install",
            f"pip=={PIP_VERSION}",
        ],
        check=True,
    )


def _run_hook_setup(python_path: Path, script_path: Path) -> None:
    """Run the git hook setup script using the venv Python."""
    subprocess.run([str(python_path), str(script_path)], check=True)


def main() -> int:
    """Run the standard dev environment bootstrap steps."""
    repo_root = Path(__file__).resolve().parents[1]
    venv_dir = repo_root / ".venv"
    requirements_path = repo_root / "requirements.txt"
    hooks_script = repo_root / "tools" / "setup_hooks.py"
    _create_venv(venv_dir)
    venv_python = _venv_python(venv_dir)
    if not venv_python.exists():
        raise FileNotFoundError(f"Venv Python not found at {venv_python}")
    _install_pinned_pip(venv_python)
    _install_requirements(venv_python, requirements_path)
    _run_hook_setup(venv_python, hooks_script)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
