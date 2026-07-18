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

"""Tests for feature-aware configuration descriptors and registry helpers."""

from __future__ import annotations

import pytest

from qpane.core.config_features import (
    CORE_DESCRIPTOR,
    DIAGNOSTICS_DESCRIPTOR,
    INPUT_DESCRIPTOR,
    MASK_DESCRIPTOR,
    SAM_DESCRIPTOR,
    ConfigFeatureRegistry,
    FeatureConfigDescriptor,
    MaskConfigSlice,
    iter_descriptors,
)


def test_iter_descriptors_returns_expected_order() -> None:
    descriptors = iter_descriptors()
    assert descriptors[0] is CORE_DESCRIPTOR
    assert descriptors[1] is INPUT_DESCRIPTOR
    assert descriptors[2] is MASK_DESCRIPTOR
    assert descriptors[3] is DIAGNOSTICS_DESCRIPTOR
    assert descriptors[4] is SAM_DESCRIPTOR


def test_registry_rejects_duplicate_namespaces() -> None:
    registry = ConfigFeatureRegistry()
    descriptor = FeatureConfigDescriptor(namespace="mask", schema=MaskConfigSlice)
    registry.register(descriptor)
    with pytest.raises(ValueError):
        registry.register(descriptor)


def test_core_defaults_clone_mutable_members() -> None:
    first = CORE_DESCRIPTOR.create_defaults()
    second = CORE_DESCRIPTOR.create_defaults()
    assert first is not second
    first.concurrency["max_workers"] = 99
    assert second.concurrency["max_workers"] == 2
    assert second.concurrency["category_priorities"]["mask_stroke"] == 60
    assert second.concurrency["category_priorities"]["mask_snippet"] == 50
    first.cache.headroom_cap_mb = 1
    assert second.cache.headroom_cap_mb == 4096
