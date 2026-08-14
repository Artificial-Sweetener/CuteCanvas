#    CuteCanvas - High-performance layered image editor
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

"""Own provisioning and process handoff for isolated demo environments."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Protocol


class _FingerprintDigest(Protocol):
    """Accept bytes contributing to one environment fingerprint."""

    def update(self, value: bytes, /) -> None:
        """Add bytes to the fingerprint state."""
        ...


@dataclass(frozen=True)
class DemoTier:
    """Describe one isolated demo dependency environment."""

    extra: str | None
    sam_enabled: bool
    label: str


@dataclass(frozen=True)
class DemoLaunchSettings:
    """Describe arguments forwarded into the provisioned demo process."""

    log_level: str = "INFO"
    config_strict: bool = False
    sam_download_mode: str | None = None
    sam_model_path: str | None = None
    sam_model_url: str | None = None
    sam_model_hash: str | None = None
    navigation_trace_output: str | None = None
    navigation_document: str | None = None


DEMO_TIERS: Mapping[str, DemoTier] = MappingProxyType(
    {
        "cutecanvas": DemoTier(
            extra=None,
            sam_enabled=False,
            label="CuteCanvas",
        ),
        "cutecanvas-sam": DemoTier(
            extra="sam",
            sam_enabled=True,
            label="CuteCanvas + SAM",
        ),
    }
)


class DemoEnvironmentError(RuntimeError):
    """Report a demo environment that cannot import the application."""


class DemoEnvironmentManager:
    """Provision tier environments and launch the demo inside them."""

    _MARKER_NAME = ".cutecanvas-install-fingerprint"

    def __init__(self, entry_point: Path) -> None:
        """Bind environment paths to the demo entry point."""
        self._entry_point = entry_point.resolve()
        self._environment_root = self._entry_point.parent
        self._project_root = self._environment_root.parent
        self._workspace_root = self._project_root.parent.parent
        self._ferrastra_root = self._project_root.parent / "ferrastra"
        self._qpane_root = self._project_root.parent / "qpane"

    def environment_dir(self, tier: str) -> Path:
        """Return the isolated environment directory for a tier."""
        self._tier(tier)
        return self._environment_root / f"venv-{tier}"

    def python_path(self, tier: str) -> Path:
        """Return the tier environment's Python executable."""
        executable_dir = "Scripts" if sys.platform.startswith("win") else "bin"
        executable = "python.exe" if sys.platform.startswith("win") else "python"
        return self.environment_dir(tier) / executable_dir / executable

    def is_current_process(self, tier: str) -> bool:
        """Return whether this process already uses the requested environment."""
        try:
            return Path(sys.executable).resolve() == self.python_path(tier).resolve()
        except (OSError, RuntimeError):
            return False

    def ensure_ready(self, tier: str, *, rebuild: bool = False) -> None:
        """Provision a tier and verify that it imports the real demo graph."""
        environment_dir = self.environment_dir(tier)
        if rebuild and environment_dir.exists():
            self._validate_removal_target(environment_dir)
            shutil.rmtree(environment_dir)
        if not self.python_path(tier).exists():
            environment_dir.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [sys.executable, "-m", "venv", str(environment_dir)],
                check=True,
            )
        if self._installed_fingerprint(tier) != self._required_fingerprint(tier):
            self._install(tier)
        probe = self._probe_demo_import(tier)
        if probe.returncode == 0:
            return
        self._install(tier)
        probe = self._probe_demo_import(tier)
        if probe.returncode != 0:
            details = (probe.stderr or probe.stdout).strip()
            raise DemoEnvironmentError(
                f"The {tier!r} demo environment cannot import CuteCanvas: {details}"
            )

    def launch(self, tier: str, settings: DemoLaunchSettings) -> int:
        """Run the demo as a child of its requested tier environment."""
        definition = self._tier(tier)
        command = [
            str(self.python_path(tier)),
            "-m",
            "cutecanvas_demo",
            "--log-level",
            settings.log_level,
            "--skip-menu",
        ]
        if definition.sam_enabled:
            command.append("--sam")
        if settings.config_strict:
            command.append("--config-strict")
        self._append_option(
            command,
            "--navigation-trace-output",
            settings.navigation_trace_output,
        )
        self._append_option(
            command,
            "--navigation-document",
            settings.navigation_document,
        )
        if definition.sam_enabled:
            self._append_option(
                command,
                "--sam-download-mode",
                settings.sam_download_mode,
            )
            self._append_option(command, "--sam-model-path", settings.sam_model_path)
            self._append_option(command, "--sam-model-url", settings.sam_model_url)
            self._append_option(command, "--sam-model-hash", settings.sam_model_hash)
        return subprocess.call(command, cwd=self._environment_root)

    def _install(self, tier: str) -> None:
        """Install the selected project tier and record its dependency fingerprint."""
        python_path = self.python_path(tier)
        subprocess.run(
            [str(python_path), "-m", "pip", "install", "--upgrade", "pip"],
            check=True,
            cwd=self._project_root,
        )
        definition = self._tier(tier)
        ferrastra_target = str(self._ferrastra_root)
        cutecanvas_target = str(self._project_root)
        if definition.extra:
            cutecanvas_target = f"{cutecanvas_target}[{definition.extra}]"
        subprocess.run(
            [
                str(python_path),
                "-m",
                "pip",
                "install",
                "-e",
                ferrastra_target,
                "-e",
                str(self._qpane_root),
                "-e",
                cutecanvas_target,
            ],
            check=True,
            cwd=self._project_root,
        )
        self._write_fingerprint(tier)

    def _probe_demo_import(self, tier: str) -> subprocess.CompletedProcess[str]:
        """Import the same module graph used immediately after process handoff."""
        module = "demonstration.demo_window"
        symbols = "ExampleOptions, ExampleWindow"
        return subprocess.run(
            [
                str(self.python_path(tier)),
                "-c",
                (f"from {module} import {symbols}"),
            ],
            cwd=self._environment_root,
            capture_output=True,
            text=True,
            check=False,
        )

    def _required_fingerprint(self, tier: str) -> str:
        """Hash install metadata that can change a tier's dependencies."""
        digest = hashlib.sha256()
        self._update_ferrastra_fingerprint(digest)
        digest.update((self._qpane_root / "pyproject.toml").read_bytes())
        digest.update((self._project_root / "pyproject.toml").read_bytes())
        digest.update(tier.encode("utf-8"))
        return digest.hexdigest()

    def _update_ferrastra_fingerprint(self, digest: _FingerprintDigest) -> None:
        """Include native inputs whose changes require rebuilding Ferrastra."""
        paths = [
            self._workspace_root / "Cargo.toml",
            self._workspace_root / "Cargo.lock",
            self._workspace_root / "rust-toolchain.toml",
            self._ferrastra_root / "pyproject.toml",
        ]
        paths.extend(sorted((self._ferrastra_root / "src").rglob("*.py")))
        for crate in sorted((self._workspace_root / "crates").glob("ferrastra-*")):
            paths.append(crate / "Cargo.toml")
            paths.extend(sorted((crate / "src").rglob("*.rs")))
        for path in paths:
            if not path.is_file():
                continue
            digest.update(
                path.relative_to(self._workspace_root).as_posix().encode("utf-8")
            )
            digest.update(path.read_bytes())

    def _write_fingerprint(self, tier: str) -> None:
        """Record the successfully installed metadata fingerprint."""
        self._fingerprint_path(tier).write_text(
            self._required_fingerprint(tier),
            encoding="utf-8",
        )

    def _installed_fingerprint(self, tier: str) -> str | None:
        """Read the fingerprint associated with the current tier installation."""
        try:
            return self._fingerprint_path(tier).read_text(encoding="utf-8").strip()
        except OSError:
            return None

    def _fingerprint_path(self, tier: str) -> Path:
        """Return the tier installation marker path."""
        return self.environment_dir(tier) / self._MARKER_NAME

    def _validate_removal_target(self, target: Path) -> None:
        """Reject recursive removal outside the owned environment directory."""
        resolved = target.resolve()
        if resolved.parent != self._environment_root or not resolved.name.startswith(
            "venv-"
        ):
            raise DemoEnvironmentError(f"Refusing to remove demo path: {resolved}")

    @staticmethod
    def _append_option(command: list[str], name: str, value: str | None) -> None:
        """Append a valued command option when configured."""
        if value:
            command.extend([name, value])

    @staticmethod
    def _tier(tier: str) -> DemoTier:
        """Return a validated tier definition."""
        try:
            return DEMO_TIERS[tier]
        except KeyError as exc:
            raise ValueError(f"Unknown demo tier: {tier}") from exc
