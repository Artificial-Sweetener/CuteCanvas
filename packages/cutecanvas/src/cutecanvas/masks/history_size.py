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

"""Estimate detached memory retained by mask history commands."""

from __future__ import annotations

from cutecanvas.coverage import CoverageDocument, CoverageStateSnapshot

from ..raster.sparse_grid import SparseRasterSnapshot
from .coverage_history import MaskCoverageCommand, MaskRetainedCoverageCommand
from .mask_undo import MaskImageCommand, MaskPatchCommand, MaskUndoCommand
from .raster_structure_history import MaskRasterStructureCommand
from .surface_history import MaskSurfaceCommand


def mask_command_bytes(command: MaskUndoCommand) -> int:
    """Estimate detached bytes retained exclusively by one mask command."""
    if isinstance(command, MaskPatchCommand):
        return sum(
            patch.before.sizeInBytes() + patch.after.sizeInBytes() + patch.mask.nbytes
            for patch in command.patches
        )
    if isinstance(command, MaskImageCommand):
        return command.before.sizeInBytes() + command.after.sizeInBytes()
    if isinstance(command, MaskSurfaceCommand):
        return _state_bytes(command.before) + _state_bytes(command.after)
    if isinstance(command, MaskRasterStructureCommand):
        return _state_bytes(command.before.raster) + _state_bytes(command.after.raster)
    if isinstance(command, MaskCoverageCommand):
        return (
            _state_bytes(command.before.raster)
            + _state_bytes(command.after.raster)
            + _document_bytes(command.before.retained)
            + _document_bytes(command.after.retained)
        )
    if isinstance(command, MaskRetainedCoverageCommand):
        return _document_bytes(command.before) + _document_bytes(command.after)
    return 0


def _document_bytes(document: CoverageDocument) -> int:
    """Estimate retained semantic payload without forcing raster evaluation."""
    segment_count = sum(len(getattr(item, "segments", ())) for item in document.items)
    return len(document.items) * 512 + segment_count * 256


def _state_bytes(snapshot: CoverageStateSnapshot) -> int:
    """Return detached bytes retained by one dense or sparse state."""
    if isinstance(snapshot, SparseRasterSnapshot):
        return snapshot.retained_bytes
    return snapshot.pixels.nbytes


__all__ = ["mask_command_bytes"]
