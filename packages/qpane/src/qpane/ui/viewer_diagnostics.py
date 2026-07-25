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
"""Live diagnostics assembly and preference lifecycle for QPane viewers."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QWidget

from ..core import Config, Diagnostics, DiagnosticsProvider, DiagnosticsSnapshot
from ..execution import ExecutionRuntime
from ..rendering.presenter import RenderingPresenter
from ..rendering.pyramid import PyramidManager
from ..types import DiagnosticRecord
from .diagnostics_controller import DiagnosticsOverlayController
from .status import create_status_overlay

if TYPE_CHECKING:
    from ..viewer import QPane


class ViewerDiagnostics:
    """Own diagnostics producers, live overlay state, and configuration."""

    def __init__(
        self,
        *,
        pane: QPane,
        presenter: RenderingPresenter,
        pyramids: PyramidManager,
        execution_runtime: ExecutionRuntime,
        overlay_changed: Callable[[bool], None],
        detail_changed: Callable[[str, bool], None],
    ) -> None:
        """Assemble source-neutral diagnostic providers for one viewer."""
        self._pane = pane
        self._diagnostics = Diagnostics(pane)
        self._diagnostics.register_core_providers(
            lambda: presenter,
            pyramid_accessor=lambda: pyramids,
        )
        self._diagnostics.register_cache_providers(
            self._cache_summary_provider(presenter, pyramids),
            tier="core",
        )
        self._diagnostics.register_cache_providers(
            self._cache_detail_provider(presenter, pyramids),
            tier="detail",
        )
        self._diagnostics.register_provider(
            self._execution_summary_provider(execution_runtime),
            domain="executor",
            tier="detail",
        )
        self._diagnostics.register_provider(
            self._retry_provider(presenter, pyramids),
            domain="retry",
            tier="detail",
        )
        self._execution_subscription = execution_runtime.subscribe_diagnostics(
            lambda _snapshots: self._diagnostics.set_dirty("executor")
        )
        self._overlay = DiagnosticsOverlayController(pane)
        self._overlay.setOverlayChangedCallback(overlay_changed)
        self._overlay.setDetailChangedCallback(detail_changed)

    def close(self) -> None:
        """Stop observing execution diagnostics for the viewer lifetime."""
        self._execution_subscription.close()

    @property
    def broker(self) -> Diagnostics:
        """Return the live diagnostics broker."""
        return self._diagnostics

    def gather(self) -> DiagnosticsSnapshot:
        """Collect a current source-neutral diagnostics snapshot."""
        return self._diagnostics.gather()

    def create_status_overlay(self, parent: QWidget | None = None) -> QWidget:
        """Create a live diagnostics HUD bound to the viewer."""
        return create_status_overlay(self._pane, parent=parent)

    def set_overlay_enabled(self, enabled: bool) -> None:
        """Show or hide the built-in live diagnostics HUD."""
        self._overlay.setOverlayEnabled(bool(enabled))

    def overlay_enabled(self) -> bool:
        """Return whether the live diagnostics HUD is visible."""
        return self._overlay.overlayEnabled()

    def domains(self) -> tuple[str, ...]:
        """Return optional live diagnostics detail domains."""
        return self._overlay.domains()

    def set_domain_enabled(self, domain: str, enabled: bool) -> None:
        """Enable or disable one validated detail domain."""
        if domain not in self.domains():
            raise ValueError(f"Unknown diagnostics domain: {domain}")
        self._overlay.setDomainEnabled(domain, bool(enabled))

    def domain_enabled(self, domain: str) -> bool:
        """Return whether one optional detail domain is enabled."""
        return self._overlay.domainEnabled(domain)

    def register_provider(
        self,
        provider: DiagnosticsProvider,
        *,
        domain: str,
        detail: bool,
    ) -> None:
        """Add one host diagnostics provider to the broker."""
        self._diagnostics.register_provider(
            provider,
            domain=domain,
            tier="detail" if detail else "core",
        )

    def validate_preferences(self, config: Config) -> None:
        """Reject unknown configured domains before collaborators mutate."""
        configured = tuple(config.diagnostics_domains_enabled or ())
        unknown = tuple(domain for domain in configured if domain not in self.domains())
        if unknown:
            raise ValueError(
                "Unknown diagnostics domains: " + ", ".join(sorted(unknown))
            )

    def apply_preferences(self, config: Config) -> None:
        """Apply validated detail-domain and overlay preferences."""
        self.validate_preferences(config)
        configured = set(config.diagnostics_domains_enabled or ())
        for domain in self.domains():
            self.set_domain_enabled(domain, domain in configured)
        self.set_overlay_enabled(bool(config.diagnostics_overlay_enabled))

    def mark_render_dirty(self) -> None:
        """Invalidate render diagnostics after asynchronous or viewport work."""
        self._diagnostics.set_dirty("render")
        self._diagnostics.set_dirty("cache")

    @staticmethod
    def _cache_summary_provider(
        presenter: RenderingPresenter,
        pyramids: PyramidManager,
    ) -> DiagnosticsProvider:
        """Build a provider for aggregate standalone renderer cache usage."""

        def _provider(_pane: QPane) -> tuple[DiagnosticRecord, ...]:
            """Collect aggregate tile and pyramid usage without a coordinator."""
            tiles = presenter.tile_manager.snapshot_metrics()
            pyramid = pyramids.snapshot_metrics()
            usage = tiles.cache_bytes + pyramid.cache_bytes
            limit = tiles.cache_limit + pyramid.cache_limit
            return (
                DiagnosticRecord(
                    "Cache",
                    f"{usage / (1024**2):.1f}/{limit / (1024**2):.1f} MB",
                ),
            )

        return _provider

    @staticmethod
    def _cache_detail_provider(
        presenter: RenderingPresenter,
        pyramids: PyramidManager,
    ) -> DiagnosticsProvider:
        """Build detailed rows from the renderer's actual cache owners."""

        def _provider(_pane: QPane) -> tuple[DiagnosticRecord, ...]:
            """Collect cache, work, hit, miss, and prefetch counters."""
            rows: list[DiagnosticRecord] = []
            for label, metrics in (
                ("Tiles", presenter.tile_manager.snapshot_metrics()),
                ("Pyramids", pyramids.snapshot_metrics()),
            ):
                rows.append(
                    DiagnosticRecord(
                        f"Cache|{label}",
                        (
                            f"{metrics.cache_bytes / (1024**2):.1f}/"
                            f"{metrics.cache_limit / (1024**2):.1f} MB | "
                            f"jobs={metrics.active_jobs} | hit={metrics.hits} | "
                            f"miss={metrics.misses} | "
                            f"prefetch={metrics.prefetch_completed}/"
                            f"{metrics.prefetch_requested}"
                        ),
                    )
                )
            return tuple(rows)

        return _provider

    @staticmethod
    def _execution_summary_provider(
        runtime: ExecutionRuntime,
    ) -> DiagnosticsProvider:
        """Build rows from optional backend diagnostics capabilities."""

        def _provider(_pane: QPane) -> tuple[DiagnosticRecord, ...]:
            """Aggregate configured backend snapshots without private access."""
            snapshots = runtime.execution_snapshots()
            if not snapshots:
                return ()
            accepted = sum(snapshot.accepted for snapshot in snapshots)
            pending = sum(snapshot.pending for snapshot in snapshots)
            running = sum(snapshot.running for snapshot in snapshots)
            retained = sum(snapshot.retained_bytes for snapshot in snapshots)
            rejected = sum(snapshot.rejected for snapshot in snapshots)
            rows = [
                DiagnosticRecord(
                    "Executor",
                    f"{running} running, {pending} pending, {accepted} accepted",
                ),
                DiagnosticRecord(
                    "Executor|Retained",
                    f"{retained / (1024**2):.1f} MB",
                ),
            ]
            if rejected:
                rows.append(DiagnosticRecord("Executor|Rejected", str(rejected)))
            return tuple(rows)

        return _provider

    @staticmethod
    def _retry_provider(
        presenter: RenderingPresenter,
        pyramids: PyramidManager,
    ) -> DiagnosticsProvider:
        """Build one compact row from renderer producer retry owners."""

        def _provider(_pane: QPane) -> tuple[DiagnosticRecord, ...]:
            """Read focused retry snapshots without legacy executor helpers."""
            parts: list[str] = []
            for name, owner in (
                ("tiles", presenter.tile_manager),
                ("pyramid", pyramids),
            ):
                snapshot = owner.retry_snapshot()
                category = snapshot.categories.get(name)
                if category is None:
                    continue
                if category.active or category.total_scheduled:
                    parts.append(f"{name}:{category.active}/{category.total_scheduled}")
            if not parts:
                return ()
            return (DiagnosticRecord("Retry", ", ".join(parts)),)

        return _provider
