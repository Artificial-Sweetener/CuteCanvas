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
"""Protect ownership of model checkpoints managed by the public demo."""

from __future__ import annotations

from pathlib import Path

import pytest

from demonstration.sam_checkpoint import clear_managed_checkpoint


def test_demo_clears_its_managed_checkpoint(tmp_path: Path) -> None:
    """Delete the cached checkpoint owned by the demo application."""
    checkpoint = tmp_path / "mobile_sam.pt"
    checkpoint.write_bytes(b"model")

    clear_managed_checkpoint(checkpoint, app_data_directory=tmp_path)

    assert not checkpoint.exists()


def test_demo_preserves_custom_checkpoint(tmp_path: Path) -> None:
    """Never delete a model file selected and owned by the user."""
    app_data = tmp_path / "app-data"
    custom_checkpoint = tmp_path / "models" / "custom.pt"
    custom_checkpoint.parent.mkdir()
    custom_checkpoint.write_bytes(b"model")

    with pytest.raises(ValueError, match="not managed by the demo"):
        clear_managed_checkpoint(
            custom_checkpoint,
            app_data_directory=app_data,
        )

    assert custom_checkpoint.read_bytes() == b"model"
