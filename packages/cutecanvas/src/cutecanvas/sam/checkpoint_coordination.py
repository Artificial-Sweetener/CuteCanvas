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

"""Coordinate one receiver-safe checkpoint acquisition lifetime."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject
from qpane.sdk.execution import (
    ExecutionHandle,
    ExecutionOutcome,
    ExecutionRejected,
    ExecutionRequest,
    ExecutionRequirements,
    ExecutionResource,
    ExecutionScope,
    ExecutionState,
    ExecutionUrgency,
)

from .checkpoint import CheckpointProgress, acquire_checkpoint

logger = logging.getLogger(__name__)


class CheckpointAcquisition(QObject):
    """Own one asynchronous checkpoint transfer and its publication."""

    def __init__(
        self,
        *,
        execution_scope: ExecutionScope,
        parent: QObject,
    ) -> None:
        """Bind checkpoint work to one feature and receiver lifetime."""
        super().__init__(parent)
        self._execution_scope = execution_scope.open_child(
            f"{execution_scope.owner_id}:sam-checkpoint"
        )
        self._handle: ExecutionHandle[Path, CheckpointProgress] | None = None

    def request(
        self,
        checkpoint_path: Path,
        *,
        download_mode: str,
        model_url: str,
        expected_hash: str | None,
        progress: Callable[[CheckpointProgress], None],
        completed: Callable[[Path], None],
        failed: Callable[[BaseException], None],
    ) -> bool:
        """Submit one transfer or validation request."""
        self.cancel()
        request = ExecutionRequest[Path, CheckpointProgress](
            operation="editor.sam.checkpoint.acquire",
            requirements=ExecutionRequirements(
                resource=ExecutionResource.BLOCKING_IO,
                urgency=ExecutionUrgency.BACKGROUND,
                resource_id=str(checkpoint_path),
            ),
            tags=(("download_mode", download_mode),),
            work=lambda context: acquire_checkpoint(
                checkpoint_path,
                download_mode=download_mode,
                model_url=model_url,
                expected_hash=expected_hash,
                context=context,
            ),
        )
        try:
            handle = self._execution_scope.submit(
                request,
                adopt=completed,
                progress=progress,
            )
        except ExecutionRejected as rejection:
            failed(rejection)
            return False
        self._handle = handle
        handle.add_done_callback(lambda outcome: self._settle(handle, outcome, failed))
        return True

    def cancel(self) -> bool:
        """Cancel the current acquisition when present."""
        handle = self._handle
        self._handle = None
        return bool(
            handle is not None
            and handle.cancel(reason="checkpoint acquisition replaced")
        )

    def close(self) -> None:
        """Close feature-owned checkpoint work."""
        self.cancel()
        self._execution_scope.close(reason="sam_checkpoint_shutdown")

    def _settle(
        self,
        handle: ExecutionHandle[Path, CheckpointProgress],
        outcome: ExecutionOutcome[Path],
        failed: Callable[[BaseException], None],
    ) -> None:
        """Release terminal state and publish failures once."""
        if self._handle is handle:
            self._handle = None
        if outcome.state == ExecutionState.FAILED:
            failed(outcome.error or RuntimeError("checkpoint acquisition failed"))
        elif outcome.state == ExecutionState.CANCELLED:
            logger.info("SAM checkpoint acquisition cancelled")


__all__ = ["CheckpointAcquisition"]
