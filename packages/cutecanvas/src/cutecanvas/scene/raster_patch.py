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

"""Compact immutable pixel payloads retained by raster edit history."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
from numpy.typing import NDArray


class RasterPatchEncoding(str, Enum):
    """Identify how one immutable uint8 patch payload is represented."""

    RAW = "raw"
    UNIFORM = "uniform"


@dataclass(frozen=True, slots=True)
class RasterPatch:
    """Retain exact uint8 pixels without a redundant writable array."""

    shape: tuple[int, ...]
    encoding: RasterPatchEncoding
    payload: bytes

    @classmethod
    def capture(cls, pixels: NDArray[np.uint8]) -> RasterPatch:
        """Detach pixels, using one sample when the entire patch is uniform."""
        array = np.asarray(pixels)
        if array.dtype != np.uint8 or array.ndim not in (2, 3):
            raise ValueError("raster history patches must be 2D or 3D uint8 arrays")
        contiguous = np.ascontiguousarray(array)
        if contiguous.size == 0:
            return cls(tuple(contiguous.shape), RasterPatchEncoding.RAW, b"")
        sample = contiguous[0, 0]
        if np.all(contiguous == sample):
            payload = np.asarray(sample, dtype=np.uint8).tobytes()
            return cls(tuple(contiguous.shape), RasterPatchEncoding.UNIFORM, payload)
        return cls(
            tuple(contiguous.shape),
            RasterPatchEncoding.RAW,
            contiguous.tobytes(order="C"),
        )

    @property
    def retained_bytes(self) -> int:
        """Return immutable payload bytes retained for replay."""
        return len(self.payload)

    def array(self) -> NDArray[np.uint8]:
        """Return a read-only exact array view suitable for restoration."""
        if self.encoding is RasterPatchEncoding.RAW:
            return np.frombuffer(self.payload, dtype=np.uint8).reshape(self.shape)
        sample_shape = self.shape[2:] if len(self.shape) == 3 else ()
        sample = np.frombuffer(self.payload, dtype=np.uint8).reshape(sample_shape)
        return np.broadcast_to(sample, self.shape)


__all__ = ["RasterPatch", "RasterPatchEncoding"]
