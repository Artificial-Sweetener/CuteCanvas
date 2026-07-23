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

"""Diagnostics providers for rendering-managed collaborators."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from ..types import DiagnosticRecord

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from ..viewer import QPane
logger = logging.getLogger(__name__)


def rendering_retry_provider(qpane: QPane) -> Iterable[DiagnosticRecord]:
    """Expose retry snapshot details for tile and pyramid managers."""
    rows: list[DiagnosticRecord] = []
    view = _call_accessor(qpane, "view")
    if view is not None:
        tile_manager = getattr(view, "tile_manager", None)
        tile_row = _format_retry_row(manager=tile_manager, expected_category="tiles")
        if tile_row:
            rows.append(DiagnosticRecord("Retry|Tiles", tile_row))
    catalog = _call_accessor(qpane, "catalog")
    pyramid_manager = _call_accessor(catalog, "pyramidManager")
    pyramid_row = _format_retry_row(
        manager=pyramid_manager,
        expected_category="pyramid",
    )
    if pyramid_row:
        rows.append(DiagnosticRecord("Retry|Pyramids", pyramid_row))
    return tuple(rows)


def _format_retry_row(*, manager, expected_category: str) -> str | None:
    """Return a formatted row for ``manager`` when snapshots are available."""
    snapshot = _snapshot(manager)
    if snapshot is None:
        return None
    categories = getattr(snapshot, "categories", None)
    if not isinstance(categories, dict):
        return None
    info = categories.get(expected_category)
    if info is None:
        return None
    parts: list[str] = []
    active = getattr(info, "active", None)
    if isinstance(active, int):
        parts.append(f"active={active}")
    total = getattr(info, "total_scheduled", None)
    if isinstance(total, int):
        parts.append(f"scheduled={total}")
    peak = getattr(info, "peak_active", None)
    if isinstance(peak, int) and peak > 0:
        parts.append(f"peak={peak}")
    return " ".join(parts) if parts else None


def _snapshot(manager):
    """Call ``manager.retry_snapshot`` defensively and return the result."""
    if manager is None:
        return None
    snapshot_fn = getattr(manager, "retrySnapshot", None) or getattr(
        manager, "retry_snapshot", None
    )
    if not callable(snapshot_fn):
        return None
    try:
        return snapshot_fn()
    except Exception:  # pragma: no cover - defensive guard
        logger.debug("retry_snapshot raised", exc_info=True)
    return None


def _call_accessor(owner: Any, accessor: str):
    """Invoke ``accessor`` on ``owner`` while suppressing failures."""
    if owner is None:
        return None
    candidate = getattr(owner, accessor, None)
    if not callable(candidate):
        return None
    try:
        return candidate()
    except Exception:  # pragma: no cover - defensive guard
        logger.debug(
            "%s.%s() raised during diagnostics",
            type(owner).__name__,
            accessor,
            exc_info=True,
        )
    return None
