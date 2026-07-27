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
"""Immutable hybrid raster/vector rendering values."""

from .evaluation import HybridDocumentEvaluator, combine_hybrid_coverage
from .model import (
    HybridCombineMode,
    HybridDocument,
    HybridPresentationStyle,
    HybridPrimitive,
    HybridRasterPrimitive,
    HybridRasterSampler,
    HybridVectorPrimitive,
)
from .presentation import present_hybrid_pixels, present_hybrid_sample

__all__ = [
    "HybridCombineMode",
    "HybridDocument",
    "HybridDocumentEvaluator",
    "HybridPresentationStyle",
    "HybridPrimitive",
    "HybridRasterPrimitive",
    "HybridRasterSampler",
    "HybridVectorPrimitive",
    "combine_hybrid_coverage",
    "present_hybrid_pixels",
    "present_hybrid_sample",
]
