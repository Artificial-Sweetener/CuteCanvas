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
"""Public example coverage for automatic and strict tile-size configuration."""

from __future__ import annotations

from qpane import Config
from qpane_demonstration.configuration import ViewerSettingsDialog


def test_example_preserves_automatic_tile_size_by_default(qapp) -> None:
    """The QPane settings example should expose the shipped automatic policy."""
    dialog = ViewerSettingsDialog(Config(), ())
    try:
        assert dialog.tile_size_mode.currentData() == "auto"
        assert not dialog.tile_size.isEnabled()
        assert dialog.config(Config()).tile_size == "auto"
    finally:
        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()


def test_example_emits_exact_fixed_tile_size(qapp) -> None:
    """The QPane settings example should preserve a host's strict integer."""
    dialog = ViewerSettingsDialog(Config(), ())
    try:
        dialog.tile_size_mode.setCurrentIndex(1)
        dialog.tile_size.setValue(1536)

        assert dialog.tile_size.isEnabled()
        assert dialog.config(Config()).tile_size == 1536
    finally:
        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()
