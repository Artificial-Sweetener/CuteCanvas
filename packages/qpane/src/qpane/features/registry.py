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

"""Feature registration definitions and dependency resolution helpers."""

from __future__ import annotations

import logging
from collections.abc import Callable, KeysView, Sequence
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
)

if TYPE_CHECKING:
    from qpane import QPane
logger = logging.getLogger(__name__)

FeatureInstaller = Callable[["QPane"], None]


class FeatureInstallError(RuntimeError):
    """Raised when feature resolution or installation fails."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        """Store an optional hint to surface alongside the failure message."""
        super().__init__(message)
        self.hint = hint


@dataclass(frozen=True)
class FeatureDefinition:
    """Declarative metadata describing an installable feature."""

    name: str
    installer: FeatureInstaller
    requires: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Ensure the dependency list is always stored as an immutable tuple."""
        object.__setattr__(self, "requires", tuple(self.requires))


class FeatureRegistry:
    """Simple in-memory registry for feature definitions."""

    def __init__(self) -> None:
        """Initialise an empty map of feature definitions."""
        self._definitions: dict[str, FeatureDefinition] = {}

    def register(self, definition: FeatureDefinition) -> None:
        """Register a feature, raising if a definition with the same name exists."""
        if definition.name in self._definitions:
            logger.error("Feature '%s' already registered", definition.name)
            raise ValueError(f"Feature '{definition.name}' already registered")
        self._definitions[definition.name] = definition

    def __contains__(self, name: str) -> bool:
        """Return whether a feature named ``name`` has been registered."""
        return name in self._definitions

    def __getitem__(self, name: str) -> FeatureDefinition:
        """Fetch the definition for ``name`` or raise ``KeyError`` when missing."""
        return self._definitions[name]

    def keys(self) -> KeysView[str]:
        """Return a dynamic view of registered feature names."""
        return self._definitions.keys()


def resolve_feature_order(
    registry: FeatureRegistry, requested: Sequence[str]
) -> list[FeatureDefinition]:
    """Topologically sort requested features and their dependencies.

    Resolution fails with ``FeatureInstallError`` if a requested feature
    does not exist or if the dependency graph contains a cycle.
    """
    order: list[FeatureDefinition] = []
    visited: set[str] = set()
    stack: list[str] = []

    def visit(name: str) -> None:
        """Resolve a feature and its dependencies using depth-first traversal."""
        if name in visited:
            return
        if name in stack:
            cycle = stack[stack.index(name) :] + [name]
            logger.error("Circular feature dependency detected: %s", " -> ".join(cycle))
            raise FeatureInstallError(
                f"Circular feature dependency detected: {' -> '.join(cycle)}"
            )
        stack.append(name)
        try:
            definition = registry[name]
        except KeyError as exc:
            stack.pop()
            logger.error("Feature '%s' requested but not registered", name)
            raise FeatureInstallError(f"Unknown feature '{name}'") from exc
        for dependency in definition.requires:
            visit(dependency)
        stack.pop()
        visited.add(name)
        order.append(definition)

    for item in requested:
        visit(item)
    return order
