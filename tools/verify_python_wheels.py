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
"""Build and validate QPane and CuteCanvas in an isolated consumer environment."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_QPANE = _ROOT / "packages/qpane"
_CUTECANVAS = _ROOT / "packages/cutecanvas"

_QPANE_CHECK = """
import importlib.util
from pathlib import Path
import qpane

package = Path(qpane.__file__).resolve().parent
environment = Path(__ENVIRONMENT__).resolve()
assert package.is_relative_to(environment)
assert importlib.util.find_spec("cutecanvas") is None
assert (package / "qpane.pyi").is_file()
assert (package / "py.typed").is_file()
"""

_CUTECANVAS_CHECK = """
from pathlib import Path
import cutecanvas
import qpane

environment = Path(__ENVIRONMENT__).resolve()
canvas = Path(cutecanvas.__file__).resolve().parent
pane = Path(qpane.__file__).resolve().parent
assert canvas.is_relative_to(environment)
assert pane.is_relative_to(environment)
assert (canvas / "cutecanvas.pyi").is_file()
assert (canvas / "py.typed").is_file()
"""


def run() -> None:
    """Build both wheels and exercise their declared dependency direction."""
    with tempfile.TemporaryDirectory(prefix="qpane-wheels-") as temporary:
        temporary_root = Path(temporary)
        distribution = temporary_root / "dist"
        _build(_QPANE, distribution)
        _build(_CUTECANVAS, distribution)
        qpane_wheel = _single_wheel(distribution, "qpane")
        cutecanvas_wheel = _single_wheel(distribution, "cutecanvas")

        environment = temporary_root / "consumer-environment"
        venv.EnvBuilder(with_pip=True).create(environment)
        interpreter = _environment_python(environment)
        _run(str(interpreter), "-m", "pip", "install", str(qpane_wheel))
        _run_isolated(interpreter, environment, temporary_root, _QPANE_CHECK)
        _run(str(interpreter), "-m", "pip", "install", str(cutecanvas_wheel))
        _run_isolated(interpreter, environment, temporary_root, _CUTECANVAS_CHECK)
    print(
        "SUCCESS: QPane installs without CuteCanvas; CuteCanvas installs against "
        "the built QPane wheel using only declared dependencies."
    )


def _build(package: Path, distribution: Path) -> None:
    """Build one wheel into the shared temporary distribution directory."""
    _run(
        sys.executable,
        "-m",
        "build",
        "--wheel",
        "--outdir",
        str(distribution),
        str(package),
    )


def _single_wheel(distribution: Path, package: str) -> Path:
    """Return exactly one wheel for ``package``."""
    wheels = tuple(distribution.glob(f"{package}-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"expected one {package} wheel, found {len(wheels)}")
    return wheels[0]


def _run_isolated(
    interpreter: Path,
    environment: Path,
    working_directory: Path,
    source: str,
) -> None:
    """Run one import probe without repository or user-site leakage."""
    check = source.replace("__ENVIRONMENT__", repr(str(environment)))
    _run(
        str(interpreter),
        "-I",
        "-c",
        check,
        cwd=working_directory,
        environment={"PYTHONNOUSERSITE": "1"},
    )


def _environment_python(environment: Path) -> Path:
    """Return the platform-specific interpreter inside ``environment``."""
    if os.name == "nt":
        return environment / "Scripts/python.exe"
    return environment / "bin/python"


def _run(
    executable: str,
    *arguments: str,
    cwd: Path | None = None,
    environment: dict[str, str] | None = None,
) -> None:
    """Run one checked build, install, or import command."""
    command_environment = os.environ.copy()
    command_environment.update(environment or {})
    subprocess.run(
        (executable, *arguments),
        cwd=cwd or _ROOT,
        env=command_environment,
        check=True,
    )


if __name__ == "__main__":
    run()
