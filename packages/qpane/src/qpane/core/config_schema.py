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
"""Composable configuration schema values shared with QPane extensions."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TypeVar

from ..features import FeatureInstallError

T = TypeVar("T")
ConfigValidator = Callable[[object], None]


@dataclass(frozen=True)
class FeatureConfigDescriptor:
    """Describe one independently owned configuration namespace."""

    namespace: str
    schema: type[object]
    requires: tuple[str, ...] = ()
    title: str | None = None
    description: str | None = None
    validators: tuple[ConfigValidator, ...] = ()

    def create_defaults(self) -> object:
        """Return a fresh schema instance populated with defaults."""
        return self.schema()  # type: ignore[call-arg]


class ConfigFeatureRegistry:
    """Own an ordered set of uniquely named configuration namespaces."""

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._descriptors: dict[str, FeatureConfigDescriptor] = {}

    def register(self, descriptor: FeatureConfigDescriptor) -> None:
        """Register ``descriptor`` while rejecting duplicate ownership."""
        if descriptor.namespace in self._descriptors:
            raise ValueError(f"Duplicate config namespace: {descriptor.namespace}")
        self._descriptors[descriptor.namespace] = descriptor

    def values(self) -> tuple[FeatureConfigDescriptor, ...]:
        """Return descriptors in registration order."""
        return tuple(self._descriptors.values())

    def as_mapping(self) -> Mapping[str, FeatureConfigDescriptor]:
        """Return a detached namespace mapping."""
        return dict(self._descriptors)


def require_feature_slice(namespace: str, slice_type: type[T], source: object) -> T:
    """Resolve a typed namespace slice from a feature-aware config source."""
    if isinstance(source, slice_type):
        return source
    for_feature = getattr(source, "for_feature", None)
    if callable(for_feature):
        slice_obj = for_feature(namespace)
        if isinstance(slice_obj, slice_type):
            return slice_obj
        raise TypeError(
            f"Feature '{namespace}' slice resolved to unexpected type: {type(slice_obj)!r}"
        )
    raise FeatureInstallError(
        f"Feature '{namespace}' configuration is unavailable; pass feature-aware settings."
    )
