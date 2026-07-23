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

"""Coordinate feature registry construction and installation."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from importlib import import_module
from typing import TYPE_CHECKING

from qpane.sdk.configuration import FeatureConfigDescriptor
from qpane.sdk.features import (
    FeatureDefinition,
    FeatureInstallError,
    FeatureRegistry,
    resolve_feature_order,
)

from .config_features import iter_descriptors
from .fallbacks import FeatureFailure

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from ..canvas import CuteCanvas
    from .fallbacks import FeatureFallbacks


@dataclass(frozen=True)
class FeatureInstallSummary:
    """Result of a feature installation pass."""

    installed: tuple[str, ...]
    failed: dict[str, FeatureFailure]
    registry: FeatureRegistry
    config_descriptors: tuple[FeatureConfigDescriptor, ...]

    def failure_messages(self) -> dict[str, str]:
        """Return failure reasons with any available hints applied."""
        return {name: failure.formatted() for name, failure in self.failed.items()}


@dataclass(frozen=True)
class _FeatureSpec:
    """Declarative description of a feature installer entrypoint."""

    name: str
    module_path: str
    installer_name: str
    requires: tuple[str, ...] = ()
    missing_module_message: str = ""
    missing_attr_message: str = ""
    hint: str | None = None


_DEFAULT_FEATURE_SPECS: tuple[_FeatureSpec, ...] = (
    _FeatureSpec(
        name="mask",
        module_path="cutecanvas.masks.install",
        installer_name="install_mask_feature",
        missing_module_message="Missing mask feature module.",
        missing_attr_message="Mask feature installer is unavailable.",
        hint="Install CuteCanvas to enable mask editing.",
    ),
    _FeatureSpec(
        name="sam",
        module_path="cutecanvas.masks.sam_feature",
        installer_name="install_sam_feature",
        requires=("mask",),
        missing_module_message="Missing SAM feature module.",
        missing_attr_message="SAM feature installer is unavailable.",
        hint="Install the SAM extras via 'pip install cutecanvas[sam]'.",
    ),
)


def default_feature_selection() -> tuple[str, ...]:
    """Return the default feature activation order."""
    return ()


class FeatureCoordinator:
    """Prepare and install optional QPane features in dependency order."""

    def __init__(self, qpane: CuteCanvas, fallbacks: FeatureFallbacks) -> None:
        """Store the QPane reference and fallback tracker used during installs."""
        self._qpane = qpane
        self._fallbacks = fallbacks

    def install(self, requested: Sequence[str]) -> FeatureInstallSummary:
        """Resolve and install the requested feature set.

        Args:
            requested: Sequence of feature names to activate for the QPane instance.
                Unknown names are recorded as failures and ignored for dependency resolution.

        Returns:
            A summary capturing installed features, recorded failures (with hints),
            and the registry snapshot used for dependency analysis.
        """
        registry = self._build_registry()
        installed: list[str] = []
        failed: dict[str, FeatureFailure] = {}
        completed: set[str] = set()
        unknown = [name for name in requested if name not in registry]
        for name in unknown:
            failure = FeatureFailure(message="Requested feature is not registered.")
            logger.warning(
                "Ignoring unknown feature '%s' requested for installation", name
            )
            failed[name] = failure
            self._fallbacks.record_failure(name, failure)
        filtered_request = [name for name in requested if name in registry]
        ordered = resolve_feature_order(registry, filtered_request)
        for definition in ordered:
            missing = [dep for dep in definition.requires if dep not in completed]
            if missing:
                reason = "Missing dependencies: " + ", ".join(sorted(missing))
                failure = FeatureFailure(message=reason)
                failed[definition.name] = failure
                self._fallbacks.record_failure(definition.name, failure)
                continue
            try:
                definition.installer(self._qpane)
            except FeatureInstallError as exc:
                failure = FeatureFailure(
                    message=str(exc),
                    hint=getattr(exc, "hint", None),
                    cause=exc.__cause__ or exc.__context__,
                )
                failed[definition.name] = failure
                self._fallbacks.record_failure(definition.name, failure)
                continue
            installed.append(definition.name)
            completed.add(definition.name)
            self._fallbacks.record_success(definition.name)
        return FeatureInstallSummary(
            installed=tuple(installed),
            failed=failed,
            registry=registry,
            config_descriptors=iter_descriptors(),
        )

    # Internal helpers -----------------------------------------------------
    def _build_registry(self) -> FeatureRegistry:
        """Construct the feature registry for this QPane instance.

        The registry is derived from the declarative specs in ``_DEFAULT_FEATURE_SPECS``
        so installers stay centralized and easy to extend.
        """
        registry = FeatureRegistry()
        for spec in _DEFAULT_FEATURE_SPECS:
            _register_feature(registry, spec)
        return registry


def _register_feature(registry: FeatureRegistry, spec: _FeatureSpec) -> None:
    """Register a feature using the provided declarative specification."""

    def _installer(qpane: CuteCanvas) -> None:
        """Import the feature module and invoke the declared installer."""
        try:
            module = import_module(spec.module_path)
        except ImportError as exc:
            message = spec.missing_module_message or (
                f"Missing module '{spec.module_path}' for feature '{spec.name}'."
            )
            raise FeatureInstallError(message, hint=spec.hint) from exc
        try:
            installer = getattr(module, spec.installer_name)
        except AttributeError as exc:
            message = spec.missing_attr_message or (
                f"Installer '{spec.installer_name}' not found in '{spec.module_path}'."
            )
            raise FeatureInstallError(message, hint=spec.hint) from exc
        installer(qpane)

    registry.register(
        FeatureDefinition(
            name=spec.name,
            installer=_installer,
            requires=spec.requires,
        )
    )
