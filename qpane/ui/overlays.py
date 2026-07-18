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

"""Overlay resume helpers shared across QPane and the interaction delegate."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover - import cycle guards
    from ..qpane import QPane
    from ..tools.delegate import ToolInteractionDelegate


def resume_overlays(interaction: ToolInteractionDelegate) -> None:
    """Clear overlay suspension flags on the interaction delegate.

    Args:
        interaction: Tool delegate owning the overlay suspension state.
    """
    interaction.overlays_suspended = False
    interaction.overlays_resume_pending = False


def resume_overlays_and_update(
    qpane: QPane, interaction: ToolInteractionDelegate
) -> None:
    """Resume overlays and trigger a repaint on `qpane`.

    Args:
        qpane: QPane whose viewport should repaint once overlays resume.
        interaction: Tool delegate whose overlay suspension flags should be cleared.
    """
    resume_overlays(interaction)
    qpane.update()


def maybe_resume_overlays(qpane: QPane, interaction: ToolInteractionDelegate) -> None:
    """Resume overlays once mask activation has completed for the active image.

    Args:
        qpane: QPane providing catalog and mask workflow access.
        interaction: Tool delegate whose overlays are currently suspended.

    Side effects:
        Logs warnings when collaborators are unavailable and force-resumes overlays on failure.
    """
    if not (interaction.overlays_suspended and interaction.overlays_resume_pending):
        return
    current_id = None
    try:
        catalog = qpane.catalog()
    except AttributeError:
        logger.warning(
            "maybe_resume_overlays: QPane catalog() unavailable; continuing without image context."
        )
    else:
        try:
            current_id = catalog.currentImageID()
        except Exception:
            logger.exception(
                "maybe_resume_overlays: Failed to read current image id; resuming without navigation context."
            )
    workflow = qpane._masks_controller
    try:
        activation_pending = workflow.is_activation_pending(current_id)
    except Exception:
        logger.exception(
            "maybe_resume_overlays: Masks workflow failed to report activation status; resuming overlays defensively."
        )
        resume_overlays(interaction)
        return
    if activation_pending:
        return
    resume_overlays(interaction)
