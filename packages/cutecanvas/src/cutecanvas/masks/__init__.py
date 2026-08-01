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

"""Mask domain delegates for the CuteCanvas widget."""

from .autosave import AutosaveManager
from .autosave_coordination import should_enable_mask_autosave
from .delegate import MaskDelegate
from .export import MaskExportSnapshot
from .mask import MaskAssetStore, MaskLayer
from .mask_controller import MaskController
from .mask_diagnostics import MaskStrokeDiagnostics
from .mask_service import MaskService
from .mask_undo import MaskPatch, MaskUndoState
from .workflow import Masks

__all__ = (
    "AutosaveManager",
    "MaskAssetStore",
    "MaskController",
    "MaskDelegate",
    "MaskExportSnapshot",
    "MaskLayer",
    "MaskPatch",
    "MaskService",
    "MaskStrokeDiagnostics",
    "MaskUndoState",
    "Masks",
    "should_enable_mask_autosave",
)
