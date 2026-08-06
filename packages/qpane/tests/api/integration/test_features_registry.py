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

import pytest
from qpane.features import (
    FeatureDefinition,
    FeatureInstallError,
    FeatureRegistry,
    resolve_feature_order,
)


def test_resolve_feature_order_respects_dependencies():
    registry = FeatureRegistry()
    registry.register(FeatureDefinition(name="base", installer=lambda qpane: None))
    registry.register(
        FeatureDefinition(
            name="addon",
            installer=lambda qpane: None,
            requires=("base",),
        )
    )
    ordered = resolve_feature_order(registry, ("addon",))
    assert [item.name for item in ordered] == ["base", "addon"]


def test_resolve_feature_order_unknown_feature_raises():
    registry = FeatureRegistry()
    with pytest.raises(FeatureInstallError):
        resolve_feature_order(registry, ("missing",))


def test_resolve_feature_order_detects_cycles():
    registry = FeatureRegistry()
    registry.register(
        FeatureDefinition(
            name="a",
            installer=lambda qpane: None,
            requires=("b",),
        )
    )
    registry.register(
        FeatureDefinition(
            name="b",
            installer=lambda qpane: None,
            requires=("a",),
        )
    )
    with pytest.raises(FeatureInstallError):
        resolve_feature_order(registry, ("a",))


def test_feature_registry_prevents_duplicates():
    registry = FeatureRegistry()
    registry.register(FeatureDefinition(name="unique", installer=lambda qpane: None))
    with pytest.raises(ValueError):
        registry.register(
            FeatureDefinition(name="unique", installer=lambda qpane: None)
        )
