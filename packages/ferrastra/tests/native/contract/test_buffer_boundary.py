#    Ferrastra - CPU-first native graphics product engine
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

"""Prove Python byte-buffer validation and canonical source adoption."""

from __future__ import annotations

import pytest

from ferrastra import BufferError, Engine


def test_padded_and_tight_buffers_produce_one_canonical_revision() -> None:
    """Discard row padding while preserving exact RGBA8 source identity."""
    engine = Engine()
    tight = bytes(range(16))
    padded = bytes(range(8)) + b"pad!" + bytes(range(8, 16)) + b"pad!"

    tight_revision = engine.add_rgba8(tight, 2, 2)
    padded_revision = engine.add_rgba8(memoryview(padded), 2, 2, stride_bytes=12)

    assert padded_revision == tight_revision


@pytest.mark.parametrize(
    ("data", "match"),
    [
        (memoryview(bytes(range(16)))[::2], "C-contiguous"),
        (memoryview(bytes(range(16))).cast("B", shape=(2, 8)), "one-dimensional"),
        (bytes(range(15)), "shorter"),
    ],
)
def test_invalid_buffer_layouts_fail_before_source_publication(
    data: bytes | memoryview, match: str
) -> None:
    """Reject noncontiguous, shaped, and undersized buffers at the FFI boundary."""
    with pytest.raises(BufferError, match=match):
        Engine().add_rgba8(data, 2, 2)
