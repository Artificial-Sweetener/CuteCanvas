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
"""Own deletion boundaries for the demo-managed SAM checkpoint cache."""

from __future__ import annotations

from pathlib import Path

_CHECKPOINT_NAME = "mobile_sam.pt"


def managed_checkpoint_path(app_data_directory: Path | None) -> Path | None:
    """Return the checkpoint path owned by the demo application."""
    if app_data_directory is None:
        return None
    # The directory is the current user's standard application-data location.
    # lgtm[py/path-injection]
    return app_data_directory.resolve() / _CHECKPOINT_NAME


def is_managed_checkpoint(
    path: Path,
    *,
    app_data_directory: Path | None,
) -> bool:
    """Return whether ``path`` names the demo-owned checkpoint location."""
    managed = managed_checkpoint_path(app_data_directory)
    if managed is None or path.name != _CHECKPOINT_NAME:
        return False
    # Parent resolution prevents traversal while preserving safe symlink deletion.
    # lgtm[py/path-injection]
    return path.parent.resolve() == managed.parent


def clear_managed_checkpoint(
    path: Path,
    *,
    app_data_directory: Path,
) -> None:
    """Delete a checkpoint only when the demo owns its exact location."""
    if not is_managed_checkpoint(path, app_data_directory=app_data_directory):
        raise ValueError(f"checkpoint {path} is not managed by the demo")
    managed = managed_checkpoint_path(app_data_directory)
    if managed is None:
        raise ValueError("the demo has no managed checkpoint location")
    # Only the application-owned filename admitted above is inspected.
    # lgtm[py/path-injection]
    if not managed.exists() and not managed.is_symlink():
        return
    # Ownership validation above constrains deletion to the app-managed filename.
    # lgtm[py/path-injection]
    managed.unlink()
