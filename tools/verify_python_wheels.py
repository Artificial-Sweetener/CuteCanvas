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

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from tools.release.artifact_validation import read_wheel_metadata
from tools.release.products import PRODUCTS, format_version, parse_stable_version

_ROOT = Path(__file__).resolve().parents[1]
_FERRASTRA = _ROOT / "packages/ferrastra"
_QPANE = _ROOT / "packages/qpane"
_CUTECANVAS = _ROOT / "packages/cutecanvas"
_PRODUCTS = {canonicalize_name(name) for name in ("ferrastra", "qpane", "cutecanvas")}

_QPANE_CHECK = """
import importlib.util
from pathlib import Path
import ferrastra
import qpane
from PySide6.QtGui import QColor, QImage
from qpane.execution.cancellation import CancellationToken
from qpane.ferrastra import generate_exact_pyramid_levels

package = Path(qpane.__file__).resolve().parent
native_package = Path(ferrastra.__file__).resolve().parent
environment = Path(__ENVIRONMENT__).resolve()
assert package.is_relative_to(environment)
assert native_package.is_relative_to(environment)
assert importlib.util.find_spec("cutecanvas") is None
assert (package / "qpane.pyi").is_file()
assert (package / "py.typed").is_file()
source = QImage(8, 4, QImage.Format_ARGB32_Premultiplied)
source.fill(QColor(65, 105, 225, 255))
levels = generate_exact_pyramid_levels(source, 1, CancellationToken()).levels
assert tuple(levels) == (0.5, 0.25)
assert [level.size().toTuple() for level in levels.values()] == [(4, 2), (2, 1)]
assert all(level.pixelColor(0, 0) == QColor(65, 105, 225, 255) for level in levels.values())
"""

_CUTECANVAS_CHECK = """
from pathlib import Path
import cutecanvas
import ferrastra
import qpane

environment = Path(__ENVIRONMENT__).resolve()
canvas = Path(cutecanvas.__file__).resolve().parent
native_package = Path(ferrastra.__file__).resolve().parent
pane = Path(qpane.__file__).resolve().parent
assert canvas.is_relative_to(environment)
assert native_package.is_relative_to(environment)
assert pane.is_relative_to(environment)
assert (canvas / "cutecanvas.pyi").is_file()
assert (canvas / "py.typed").is_file()
"""


def run() -> None:
    """Build all product wheels and exercise their declared dependency direction."""
    with tempfile.TemporaryDirectory(prefix="qpane-wheels-") as temporary:
        temporary_root = Path(temporary)
        distribution = temporary_root / "dist"
        build_environment = _stable_build_environment()
        _build(_FERRASTRA, distribution, build_environment)
        _build(_QPANE, distribution, build_environment)
        _build(_CUTECANVAS, distribution, build_environment)
        _single_wheel(distribution, "ferrastra")
        qpane_wheel = _single_wheel(distribution, "qpane")
        cutecanvas_wheel = _single_wheel(distribution, "cutecanvas")
        _download_wheelhouse_dependencies(distribution)

        qpane_environment = temporary_root / "qpane-consumer-environment"
        qpane_interpreter = _create_consumer_environment(qpane_environment)
        _install_local_stack(
            qpane_interpreter,
            distribution,
            "qpane",
            read_wheel_metadata(qpane_wheel).version,
        )
        _run_isolated(
            qpane_interpreter,
            qpane_environment,
            temporary_root,
            _QPANE_CHECK,
        )

        cutecanvas_environment = temporary_root / "cutecanvas-consumer-environment"
        cutecanvas_interpreter = _create_consumer_environment(cutecanvas_environment)
        _install_local_stack(
            cutecanvas_interpreter,
            distribution,
            "cutecanvas",
            read_wheel_metadata(cutecanvas_wheel).version,
        )
        _run_isolated(
            cutecanvas_interpreter,
            cutecanvas_environment,
            temporary_root,
            _CUTECANVAS_CHECK,
        )
    print(
        "SUCCESS: QPane installs with the built Ferrastra wheel and without "
        "CuteCanvas; CuteCanvas installs against the built QPane wheel using "
        "only declared dependencies."
    )


def _create_consumer_environment(environment: Path) -> Path:
    """Create an empty isolated consumer containing only its bundled pip."""
    venv.EnvBuilder(with_pip=True).create(environment)
    return _environment_python(environment)


def _install_local_stack(
    interpreter: Path,
    distribution: Path,
    package: str,
    version: str,
) -> None:
    """Resolve one product and all product dependencies in a clean transaction."""
    _run(
        str(interpreter),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-index",
        "--find-links",
        str(distribution),
        f"{package}=={version}",
    )


def _download_wheelhouse_dependencies(distribution: Path) -> None:
    """Populate transitive third-party wheels before the offline install proof."""
    requirements: set[str] = set()
    for wheel in distribution.glob("*.whl"):
        metadata = read_wheel_metadata(wheel)
        for value in metadata.requirements:
            requirement = Requirement(value)
            if canonicalize_name(requirement.name) not in _PRODUCTS:
                requirements.add(str(requirement))
    _run(
        sys.executable,
        "-m",
        "pip",
        "download",
        "--disable-pip-version-check",
        "--only-binary=:all:",
        "--dest",
        str(distribution),
        *sorted(requirements),
    )


def _stable_build_environment() -> dict[str, str]:
    """Return exact candidate or dynamically derived stable wheel versions."""
    environment: dict[str, str] = {}
    for name in ("qpane", "cutecanvas"):
        key = f"SETUPTOOLS_SCM_PRETEND_VERSION_FOR_{name.upper()}"
        configured = os.environ.get(key)
        environment[key] = configured or _next_local_version(name)
    return environment


def _next_local_version(name: str) -> str:
    """Derive a stable packaging-test version from the latest product tag."""
    product = PRODUCTS[name]
    completed = subprocess.run(
        (
            "git",
            "tag",
            "--list",
            f"{product.tag_prefix}*",
            "--sort=-version:refname",
        ),
        cwd=_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    tags = completed.stdout.splitlines()
    if not tags:
        return format_version(product.first_release)
    current = parse_stable_version(tags[0].removeprefix(product.tag_prefix))
    return format_version((current[0], current[1], current[2] + 1))


def _build(
    package: Path,
    distribution: Path,
    environment: dict[str, str],
) -> None:
    """Build one wheel into the shared temporary distribution directory."""
    _run(
        sys.executable,
        "-m",
        "build",
        "--wheel",
        "--outdir",
        str(distribution),
        str(package),
        environment=environment,
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
