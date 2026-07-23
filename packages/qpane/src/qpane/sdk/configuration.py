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
"""Supported configuration extension contracts for QPane hosts."""

from ..core.config import CacheSettings, Config, FeatureAwareConfig, diff_config_fields
from ..core.config_features import iter_descriptors
from ..core.config_schema import (
    ConfigFeatureRegistry,
    FeatureConfigDescriptor,
    require_feature_slice,
)

__all__ = (
    "CacheSettings",
    "Config",
    "ConfigFeatureRegistry",
    "FeatureAwareConfig",
    "FeatureConfigDescriptor",
    "diff_config_fields",
    "iter_descriptors",
    "require_feature_slice",
)
