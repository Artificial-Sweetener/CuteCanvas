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

"""Resolve SAM checkpoint files as detached execution products."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from qpane.sdk.execution import ExecutionTaskContext

from . import service


@dataclass(frozen=True, slots=True)
class CheckpointProgress:
    """Report downloaded and optional total checkpoint bytes."""

    downloaded: int
    total: int | None


def acquire_checkpoint(
    checkpoint_path: Path,
    *,
    download_mode: str,
    model_url: str,
    expected_hash: str | None,
    context: ExecutionTaskContext[CheckpointProgress],
) -> Path:
    """Download or validate one checkpoint with scoped progress delivery."""

    def _progress(downloaded: int, total: int | None) -> None:
        """Forward transfer progress through the execution channel."""
        context.cancellation.raise_if_cancelled()
        context.progress.report(
            CheckpointProgress(
                int(downloaded),
                None if total is None else int(total),
            )
        )

    context.cancellation.raise_if_cancelled()
    resolved = service.ensure_checkpoint(
        checkpoint_path,
        download_mode=download_mode,
        model_url=model_url,
        expected_hash=expected_hash,
        progress_callback=_progress,
    )
    context.cancellation.raise_if_cancelled()
    return Path(resolved)


__all__ = [
    "CheckpointProgress",
    "acquire_checkpoint",
]
