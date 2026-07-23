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

"""Tests covering the feature-aware configuration view."""

from __future__ import annotations

import pytest
from cutecanvas.core.config import Config
from cutecanvas.core.config_features import MASK_DESCRIPTOR
from qpane.core.config import FeatureAwareConfig
from qpane.core.config_features import CORE_DESCRIPTOR
from qpane.features import FeatureInstallError


@pytest.fixture()
def base_config() -> Config:
    return Config()


def test_for_feature_returns_slice(base_config: Config) -> None:
    view = FeatureAwareConfig(
        base_config,
        descriptors=(MASK_DESCRIPTOR,),
        installed_features=("mask",),
    )
    mask_slice = view.for_feature("mask")
    assert mask_slice.mask_undo_limit == base_config.mask_undo_limit
    mask_slice.mask_undo_limit = 999
    assert base_config.mask_undo_limit == 20


def test_for_feature_missing_feature_raises(base_config: Config) -> None:
    view = FeatureAwareConfig(
        base_config, descriptors=(MASK_DESCRIPTOR,), installed_features=()
    )
    with pytest.raises(FeatureInstallError):
        view.for_feature("mask")


def test_missing_feature_access_raises(base_config: Config) -> None:
    view = FeatureAwareConfig(
        base_config, descriptors=(MASK_DESCRIPTOR,), installed_features=()
    )
    with pytest.raises(FeatureInstallError):
        _ = view.mask_undo_limit


def test_core_descriptor_merges_into_view(base_config: Config) -> None:
    base_config.tile_size = 2048
    view = FeatureAwareConfig(
        base_config,
        descriptors=(CORE_DESCRIPTOR,),
        installed_features=(),
    )
    assert view.tile_size == 2048


def test_inactive_fields_expose_unused_namespace(base_config: Config) -> None:
    view = FeatureAwareConfig(
        base_config, descriptors=(MASK_DESCRIPTOR,), installed_features=()
    )
    inactive = view.inactive_fields()
    assert "mask" in inactive
    assert "mask_undo_limit" in inactive["mask"]


def test_unused_fields_only_include_overrides(base_config: Config) -> None:
    base_config.mask_border_enabled = True
    view = FeatureAwareConfig(
        base_config,
        descriptors=(MASK_DESCRIPTOR,),
        installed_features=(),
        override_fields={"mask_border_enabled"},
    )
    unused = view.unused_fields()
    assert unused == {"mask": ("mask_border_enabled",)}


def test_strict_mode_rejects_inactive_overrides(base_config: Config) -> None:
    base_config.mask_border_enabled = True
    with pytest.raises(ValueError):
        FeatureAwareConfig(
            base_config,
            descriptors=(MASK_DESCRIPTOR,),
            installed_features=(),
            override_fields={"mask_border_enabled"},
            strict=True,
        )
