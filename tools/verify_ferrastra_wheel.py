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
"""Build and validate Ferrastra wheel and source-distribution boundaries."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_PACKAGE = _ROOT / "packages/ferrastra"
_ISOLATED_CHECK = """
import importlib.util
import ferrastra
from ferrastra import _native

assert ferrastra.__all__ == ["__version__"]
assert ferrastra.__version__ == _native.package_version()
for forbidden in ("PySide6", "qpane", "cutecanvas"):
    assert importlib.util.find_spec(forbidden) is None
"""


def run() -> None:
    """Prove direct and source-derived wheels in isolated environments."""
    with tempfile.TemporaryDirectory(prefix="ferrastra-wheel-") as temporary:
        root = Path(temporary)
        distribution = root / "dist"
        _run(
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--sdist",
            "--outdir",
            str(distribution),
            str(_PACKAGE),
        )
        wheels = tuple(distribution.glob("ferrastra-*.whl"))
        if len(wheels) != 1:
            raise RuntimeError(f"expected one Ferrastra wheel, found {len(wheels)}")
        source_distributions = tuple(distribution.glob("ferrastra-*.tar.gz"))
        if len(source_distributions) != 1:
            raise RuntimeError(
                "expected one Ferrastra source distribution, "
                f"found {len(source_distributions)}"
            )
        _verify_wheel(wheels[0], root / "direct-wheel-environment", root)

        rebuilt_distribution = root / "rebuilt-dist"
        _run(
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--wheel-dir",
            str(rebuilt_distribution),
            str(source_distributions[0]),
        )
        rebuilt_wheels = tuple(rebuilt_distribution.glob("ferrastra-*.whl"))
        if len(rebuilt_wheels) != 1:
            raise RuntimeError(
                "expected one Ferrastra wheel rebuilt from the source distribution, "
                f"found {len(rebuilt_wheels)}"
            )
        _verify_wheel(rebuilt_wheels[0], root / "sdist-wheel-environment", root)
    print(
        "SUCCESS: Direct and source-derived Ferrastra wheels contain only the "
        "native package boundary."
    )


def _verify_wheel(wheel: Path, environment: Path, root: Path) -> None:
    """Install and validate one wheel without sibling products available."""
    venv.EnvBuilder(with_pip=True).create(environment)
    interpreter = _environment_python(environment)
    _run(str(interpreter), "-m", "pip", "install", "--no-deps", str(wheel))
    _run(
        str(interpreter),
        "-I",
        "-c",
        _ISOLATED_CHECK,
        cwd=root,
        environment={"PYTHONNOUSERSITE": "1"},
    )


def _environment_python(environment: Path) -> Path:
    """Return the platform-specific interpreter path for a virtual environment."""
    if os.name == "nt":
        return environment / "Scripts/python.exe"
    return environment / "bin/python"


def _run(
    executable: str,
    *arguments: str,
    cwd: Path | None = None,
    environment: dict[str, str] | None = None,
) -> None:
    """Run one checked command with deterministic environment additions."""
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
