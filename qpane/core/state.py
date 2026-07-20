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

"""Core configuration, feature, cache, and executor state for the QPane widget."""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QTimer

from ..cache import CacheCoordinator
from ..cache.registry import CacheRegistry
from ..concurrency.executor import (
    LiveTunableExecutorProtocol,
    QThreadPoolExecutor,
    TaskExecutorProtocol,
    TaskHandle,
    TaskRejected,
)
from ..concurrency.metrics import retry_diagnostics_provider, retry_summary_provider
from ..concurrency.thread_policy import ThreadPolicy, build_thread_policy
from ..types import DiagnosticRecord
from .config import CacheSettings, Config, FeatureAwareConfig, diff_config_fields
from .config_features import FeatureConfigDescriptor, iter_descriptors
from .diagnostics import (
    DiagnosticsProvider,
    DiagnosticsRegistry,
    DiagnosticsSnapshot,
)
from .diagnostics_broker import Diagnostics
from .fallbacks import FeatureFailure, FeatureFallbacks
from .feature_coordinator import FeatureCoordinator, default_feature_selection
from .headroom import SystemHeadroomWorker

if TYPE_CHECKING:  # pragma: no cover

    from ..qpane import QPane
MB = 1024 * 1024


logger = logging.getLogger(__name__)


def _qpane_view(qpane: QPane):
    """Return ``qpane.view()`` while tolerating partially-initialized panes."""
    try:
        return qpane.view()
    except AttributeError:
        return None


def _qpane_catalog(qpane: QPane):
    """Return ``qpane.catalog()`` if available, otherwise ``None``."""
    try:
        return qpane.catalog()
    except AttributeError:
        return None


class QPaneState:
    """Encapsulate configuration, feature, cache, executor, and diagnostics wiring behind the QPane facade."""

    def __init__(
        self,
        *,
        qpane: QPane,
        initial_config: Config | None,
        config_overrides: Mapping[str, Any] | None,
        features: Iterable[str] | None,
        task_executor: TaskExecutorProtocol | None,
        thread_policy: ThreadPolicy | Mapping[str, Any] | None,
        config_strict: bool = False,
    ) -> None:
        """Capture configuration, features, and executors for a QPane instance.

        Args:
            qpane: Owning QPane facade whose collaborators are configured by this
                state container.
            initial_config: Optional baseline :class:`Config` snapshot to start
                from instead of the global singleton.
            config_overrides: Mapping of config keys applied on top of the base.
            features: Optional iterable of feature names requested by the host.
            task_executor: Pre-built executor to reuse; when ``None`` QPaneState
                constructs and owns a single shared :class:`QThreadPoolExecutor`
                for all collaborators.
            thread_policy: :class:`ThreadPolicy` or mapping used when creating a
                managed executor.
            config_strict: Raise ``ValueError`` when overrides target inactive
                feature namespaces instead of logging warnings.
        """
        self._qpane = qpane
        base_config = initial_config.copy() if initial_config is not None else Config()
        if config_overrides:
            base_config.configure(**dict(config_overrides))
        self._base_config = base_config
        self.settings: FeatureAwareConfig = FeatureAwareConfig(base_config)
        self._requested_features = self._normalize_feature_request(features)
        self._config_strict = bool(config_strict)
        self._fallbacks = FeatureFallbacks()
        self._installed_features: list[str] = []
        self._failed_features: dict[str, FeatureFailure] = {}
        self._unused_setting_counts: Counter[str] = Counter()
        self._unused_setting_last_fields: dict[str, tuple[str, ...]] = {}
        self._validation_failures: dict[str, str] = {}
        self._executor, self._owns_executor = self._resolve_executor(
            task_executor, thread_policy
        )
        self._cache_coordinator: CacheCoordinator | None = None
        self._cache_registry: CacheRegistry | None = None
        self._diagnostics = Diagnostics(qpane)
        self._diagnostics.register_core_providers(lambda: _qpane_view(qpane))
        self._register_executor_diagnostics()
        self._attach_executor_dirty_callback()
        self._config_diagnostics_provider = self._build_config_diagnostics_provider()
        self._diagnostics.register_provider(
            self._config_diagnostics_provider,
            domain="config",
            tier="core",
        )
        self._config_descriptors: tuple[FeatureConfigDescriptor, ...] = (
            iter_descriptors()
        )
        self._compose_settings_view()
        self._missing_view_logged = False
        self._missing_presenter_logged = False
        self._missing_swap_delegate_logged = False
        self._headroom_timer: QTimer | None = None
        self._headroom_psutil_module = None
        self._headroom_psutil_missing = False
        self._last_headroom_snapshot: dict[str, object] = {}
        self._pending_headroom: tuple[SystemHeadroomWorker, TaskHandle] | None = None

    @property
    def executor(self) -> TaskExecutorProtocol:
        """Return the shared task executor for the QPane instance."""
        return self._executor

    @property
    def cache_coordinator(self) -> CacheCoordinator | None:
        """Return the cache coordinator when coordination is enabled."""
        return self._cache_coordinator

    @cache_coordinator.setter
    def cache_coordinator(self, coordinator: CacheCoordinator | None) -> None:
        """Install or clear the cache coordinator reference."""
        self._cache_coordinator = coordinator

    @property
    def cache_registry(self) -> CacheRegistry | None:
        """Return the cache registry that tracks cache consumers."""
        return self._cache_registry

    @cache_registry.setter
    def cache_registry(self, registry: CacheRegistry | None) -> None:
        """Install or clear the cache registry reference."""
        self._cache_registry = registry

    @property
    def diagnostics(self) -> Diagnostics:
        """Expose the diagnostics broker owned by this state object."""
        return self._diagnostics

    @property
    def diagnostics_registry(self) -> DiagnosticsRegistry:
        """Expose the underlying registry for callers that need the raw providers."""
        return self._diagnostics.registry

    @property
    def fallbacks(self) -> FeatureFallbacks:
        """Return the fallback tracker used during feature installation and usage."""
        return self._fallbacks

    @property
    def failed_features(self) -> Mapping[str, FeatureFailure]:
        """Expose recorded feature installation failures keyed by feature name."""
        return MappingProxyType(self._failed_features)

    @property
    def requested_features(self) -> tuple[str, ...]:
        """Return the feature sequence requested during initialization."""
        return self._requested_features

    @property
    def installed_features(self) -> tuple[str, ...]:
        """Return the feature names installed during ``FeatureCoordinator`` runs."""
        return tuple(self._installed_features)

    @property
    def config_descriptors(self) -> tuple[FeatureConfigDescriptor, ...]:
        """Expose the feature-config descriptors reported by the coordinator."""
        return self._config_descriptors

    def default_feature_selection(self) -> tuple[str, ...]:
        """Return the default ("mask", "sam") feature tuple exposed to the QPane facade."""
        return default_feature_selection()

    def normalize_feature_request(self, features) -> tuple[str, ...]:
        """Normalize incoming feature requests via the shared helper.

        Args:
            features: ``None``, a string, or an iterable of strings describing the
                requested feature set.

        Returns:
            A tuple of unique feature names preserving the requested order.
        """
        return self._normalize_feature_request(features)

    def gather_diagnostics(self) -> DiagnosticsSnapshot:
        """Collect diagnostics via the shared broker."""
        return self._diagnostics.gather()

    def _attach_executor_dirty_callback(self) -> None:
        """Forward executor diagnostics dirty events to the broker."""
        setter = getattr(self._executor, "set_dirty_callback", None)
        if not callable(setter):
            return
        setter(lambda domain="executor": self._diagnostics.set_dirty(domain))

    def register_diagnostics_provider(
        self,
        provider: DiagnosticsProvider,
        *,
        domain: str = "custom",
        tier: str = "core",
    ) -> None:
        """Register a diagnostics provider via the shared broker."""
        self._diagnostics.register_provider(provider, domain=domain, tier=tier)

    def install_features(self, requested_features: Sequence[str] | None = None) -> None:
        """Install requested features and store the registry/failure state.

        Args:
            requested_features: Optional override for the feature list provided at
                initialization. ``None`` reuses :attr:`requested_features`.
        """
        feature_names = tuple(requested_features or self._requested_features)
        coordinator = FeatureCoordinator(self._qpane, self._fallbacks)
        summary = coordinator.install(feature_names)
        self._failed_features = dict(summary.failed)
        self._installed_features = list(summary.installed)
        self._config_descriptors = summary.config_descriptors
        self._compose_settings_view()
        if summary.failed:
            for feature, failure in summary.failed.items():
                logger.warning(
                    "Feature '%s': %s; continuing without it",
                    feature,
                    failure.formatted(),
                )

    def apply_settings(self, *, config: Config | None = None, **overrides: Any) -> None:
        """Replace the active settings snapshot and propagate it to components.

        Args:
            config: Optional :class:`Config` snapshot to clone before applying
                overrides. ``None`` clones the currently active settings.
            **overrides: Keyword overrides applied after the clone is created.

        Raises:
            ValueError: When strict config mode is enabled and overrides target
                inactive feature namespaces.

        Side effects:
            Pushes configuration into the view, catalog, masks, and cache coordinator.
            Resets the brush size to the configured default when the user has not
            customized it.
        """
        old_settings = self.settings
        source = config if config is not None else self._base_config
        new_settings = source.copy()
        if overrides:
            new_settings.configure(**overrides)
        old_base_config = self._base_config
        self._base_config = new_settings
        try:
            self._compose_settings_view()
        except Exception:
            self._base_config = old_base_config
            self.settings = old_settings
            raise
        self._apply_settings_to_components(old_settings)
        self._apply_concurrency_settings()
        self.apply_cache_settings()
        self._restart_headroom_monitor()

    def _compose_settings_view(self) -> None:
        """Rebuild the feature-aware settings view exposed to callers."""
        self._unused_setting_counts.clear()
        self._unused_setting_last_fields.clear()
        active_features: Sequence[str]
        if self._installed_features:
            active_features = self._installed_features
        else:
            active_features = self._requested_features
        override_fields = diff_config_fields(self._base_config)
        self.settings = FeatureAwareConfig(
            self._base_config,
            descriptors=self._config_descriptors,
            installed_features=active_features,
            override_fields=override_fields,
            strict=self._config_strict,
        )
        self._validation_failures = self.settings.validation_failures()
        if not self._config_strict:
            self.log_unused_settings()
        self._diagnostics.set_dirty("config")

    def log_unused_settings(self) -> None:
        """Log ignored overrides that target inactive feature namespaces."""
        unused = self.settings.unused_fields()
        if not unused:
            return
        for namespace, fields in unused.items():
            if not fields:
                continue
            field_list = ", ".join(sorted(fields))
            logger.warning(
                "Ignoring config overrides (%s) because feature '%s' is inactive",
                field_list,
                namespace,
            )
            self._unused_setting_counts[namespace] += len(fields)
            self._unused_setting_last_fields[namespace] = tuple(fields)
        self._diagnostics.set_dirty("config")

    def _build_config_diagnostics_provider(self) -> DiagnosticsProvider:
        """Return a provider describing unused configuration overrides."""

        def _provider(_qpane: QPane) -> tuple[DiagnosticRecord, ...]:
            """Expose ignored override counts for diagnostics overlays."""
            records: list[DiagnosticRecord] = []
            for namespace in sorted(self._unused_setting_counts.keys()):
                count = self._unused_setting_counts[namespace]
                if count <= 0:
                    continue
                recent_fields = self._unused_setting_last_fields.get(namespace, ())
                if recent_fields:
                    detail = ", ".join(recent_fields)
                    value = f"{count} ignored ({detail})"
                else:
                    value = f"{count} ignored"
                records.append(
                    DiagnosticRecord(label=f"Config ({namespace})", value=value)
                )
            for namespace, message in sorted(self._validation_failures.items()):
                records.append(
                    DiagnosticRecord(
                        label=f"Config ({namespace})",
                        value=f"invalid ({message})",
                    )
                )
            return tuple(records)

        return _provider

    def apply_cache_settings(self) -> None:
        """Propagate cache budgets/overrides to the coordinator.

        The call is a no-op when :attr:`cache_coordinator` is ``None``.
        """
        coordinator = self._cache_coordinator
        if coordinator is None:
            return
        self._configure_cache_coordinator(coordinator)

    def _configure_cache_coordinator(self, coordinator: CacheCoordinator) -> None:
        """Apply the active cache settings to ``coordinator`` once."""
        cache_settings = self._cache_settings()
        active_budget_bytes = cache_settings.resolve_active_budget_bytes()
        coordinator.set_active_budget(active_budget_bytes)
        coordinator.set_hard_cap(cache_settings.mode.lower() == "hard")
        resolved_budgets = cache_settings.resolve_consumer_budgets_bytes(
            active_budget_bytes
        )
        overrides = cache_settings.explicit_overrides_mb()
        weights = cache_settings.weights.normalized(
            {"tiles", "pyramids", "masks", "predictors"}
        )
        consumer_map = {
            "tiles": "tiles",
            "pyramids": "pyramids",
            "masks": "mask_overlays",
            "predictors": "predictors",
        }
        for logical, consumer_id in consumer_map.items():
            if not coordinator.has_consumer(consumer_id):
                continue
            override_mb = overrides.get(logical)
            coordinator.set_consumer_override(
                consumer_id,
                None if override_mb is None else override_mb * MB,
            )
            weight = weights.get(logical, 0.0)
            coordinator.set_consumer_weight(consumer_id, weight)
            budget_bytes = resolved_budgets.get(logical)
            if budget_bytes is not None:
                coordinator.set_consumer_preferred(consumer_id, budget_bytes)

    def _restart_headroom_monitor(self) -> None:
        """Start or stop the Auto-mode headroom monitor based on the active config."""
        if self._cache_coordinator is None:
            self._stop_headroom_monitor()
            return
        mode = self._cache_settings().mode.lower()
        if mode != "auto":
            self._stop_headroom_monitor()
            return
        self._headroom_psutil_missing = False
        self._start_headroom_monitor()

    def _start_headroom_monitor(self) -> None:
        """Ensure the headroom monitor timer is running."""
        timer = self._headroom_timer
        if timer is None:
            timer = QTimer(self._qpane)
            timer.setInterval(2000)
            timer.timeout.connect(self._headroom_tick)
            self._headroom_timer = timer
        if not timer.isActive():
            timer.start()

    def _stop_headroom_monitor(self) -> None:
        """Stop the headroom monitor timer when inactive."""
        timer = self._headroom_timer
        if timer is not None:
            timer.stop()
        pending = self._pending_headroom
        self._pending_headroom = None
        if pending is not None:
            worker, handle = pending
            worker.cancel()
            self._executor.cancel(handle)

    def _headroom_tick(self) -> None:
        """Submit one system-headroom observation without blocking Qt."""
        coordinator = self._cache_coordinator
        if coordinator is None:
            self._stop_headroom_monitor()
            return
        cache_settings = self._cache_settings()
        if cache_settings.mode.lower() != "auto":
            self._stop_headroom_monitor()
            return
        if self._pending_headroom is not None:
            return
        if self._headroom_psutil_missing:
            self._apply_headroom_fallback()
            return
        worker = SystemHeadroomWorker(self._headroom_psutil_module)
        worker.connect_queued(worker.finished, self._finish_headroom_sample)
        worker.connect_queued(worker.error, self._finish_headroom_sample)
        try:
            handle = self._executor.submit(worker, category="cache_headroom")
        except TaskRejected:
            worker.deleteLater()
            return
        self._pending_headroom = (worker, handle)

    def _finish_headroom_sample(self, worker: SystemHeadroomWorker) -> None:
        """Apply one current worker observation on the GUI thread."""
        pending = self._pending_headroom
        if pending is None or pending[0] is not worker:
            return
        self._pending_headroom = None
        coordinator = self._cache_coordinator
        if coordinator is None or self._cache_settings().mode.lower() != "auto":
            return
        sample = worker.sample
        if sample is None:
            self._headroom_psutil_missing = True
            self._apply_headroom_fallback()
            return
        self._headroom_psutil_module = worker.psutil_module
        cache_settings = self._cache_settings()
        available = max(0, sample.available_bytes)
        total = max(0, sample.total_bytes)
        headroom_bytes = min(
            int(total * max(0.0, float(cache_settings.headroom_percent))),
            max(0, int(cache_settings.headroom_cap_mb)) * MB,
        )
        usage_bytes = coordinator.total_usage_bytes
        capacity_bytes = max(0, total - headroom_bytes)
        budget_bytes = min(
            max(available + usage_bytes - headroom_bytes, usage_bytes),
            capacity_bytes,
        )
        snapshot = sample.diagnostic_snapshot()
        if (
            budget_bytes != coordinator.active_budget_bytes
            or snapshot != self._last_headroom_snapshot
        ):
            coordinator.set_active_budget(budget_bytes)
            coordinator.set_headroom_snapshot(snapshot)
            self._last_headroom_snapshot = snapshot

    def _apply_headroom_fallback(self) -> None:
        """Install the conservative hard cap after observation failure."""
        coordinator = self._cache_coordinator
        if coordinator is None:
            return
        self._stop_headroom_monitor()
        coordinator.set_hard_cap(True)
        budget_bytes = 1024 * MB
        if (
            budget_bytes != coordinator.active_budget_bytes
            or self._last_headroom_snapshot
        ):
            coordinator.set_active_budget(budget_bytes)
            coordinator.set_headroom_snapshot({})
            self._last_headroom_snapshot = {}

    def build_cache_coordinator(self) -> CacheCoordinator:
        """Build a cache coordinator configured with the resolved budgets.

        Returns:
            CacheCoordinator: Fresh coordinator initialized with the aggregate
            cache budget expressed in bytes.
        """
        qpane = getattr(self, "_qpane", None)
        callback = None
        if qpane is not None:
            try:
                diagnostics = qpane.diagnostics()
            except RuntimeError:
                diagnostics = None
            if diagnostics is not None:

                def _mark_cache_dirty(domain: str = "cache") -> None:
                    """Mark cache diagnostics as dirty after coordinator updates."""
                    diagnostics.set_dirty(domain)

                callback = _mark_cache_dirty
        cache_settings = self._cache_settings()
        active_budget_bytes = cache_settings.resolve_active_budget_bytes()
        coordinator = CacheCoordinator(active_budget_bytes, dirty_callback=callback)
        self._cache_coordinator = coordinator
        self._configure_cache_coordinator(coordinator)
        self._restart_headroom_monitor()
        return coordinator

    def _cache_settings(self) -> CacheSettings:
        """Return the active :class:`CacheSettings`, defaulting to an empty struct."""
        cache_settings = getattr(self._base_config, "cache", None)
        if isinstance(cache_settings, CacheSettings):
            return cache_settings
        return CacheSettings()

    def _resolve_view_collaborators(
        self,
    ) -> tuple[
        object | None, object | None, object | None, object | None, object | None
    ]:
        """Return view, presenter, viewport, tile manager, and swap delegate via the facade."""
        try:
            view = self._qpane.view()
        except AttributeError:
            if not self._missing_view_logged:
                logger.warning(
                    "Skipping settings application because the view is unavailable"
                )
                self._missing_view_logged = True
            return None, None, None, None, None
        try:
            presenter = self._qpane.presenter()
        except AttributeError:
            presenter = None
        if presenter is None and not self._missing_presenter_logged:
            logger.warning(
                "Skipping settings application because the presenter is unavailable"
            )
            self._missing_presenter_logged = True
        viewport = (
            getattr(presenter, "viewport", None) if presenter is not None else None
        )
        tile_manager = (
            getattr(presenter, "tile_manager", None) if presenter is not None else None
        )
        try:
            swap_delegate = self._qpane.swapDelegate
        except AttributeError:
            swap_delegate = None
        if swap_delegate is None and not self._missing_swap_delegate_logged:
            logger.warning(
                "Skipping swap delegate settings because it is unavailable on the view"
            )
            self._missing_swap_delegate_logged = True
        return view, presenter, viewport, tile_manager, swap_delegate

    def _apply_settings_to_components(self, old_settings: FeatureAwareConfig) -> None:
        """Push updated settings to collaborators and refresh default brush size when used."""
        qpane = self._qpane
        catalog = _qpane_catalog(qpane)
        if catalog is not None:
            catalog.applyConfig(self.settings)
        (
            _view,
            _presenter,
            viewport,
            tile_manager,
            swap_delegate,
        ) = self._resolve_view_collaborators()
        if viewport is not None:
            viewport.applyConfig(self.settings)
        if tile_manager is not None:
            tile_manager.apply_config(self.settings)
        if swap_delegate is not None:
            swap_delegate.apply_config(self.settings)
        masks = qpane._masks_controller
        masks.apply_config(self.settings)
        if qpane.interaction.brush_size == old_settings.default_brush_size:
            qpane.interaction.brush_size = self.settings.default_brush_size

    def _apply_concurrency_settings(self) -> None:
        """Push the active concurrency configuration into the executor live."""
        executor = getattr(self, "_executor", None)
        if executor is None:
            return
        if not isinstance(executor, LiveTunableExecutorProtocol):
            logger.debug(
                "Skipping live concurrency update because executor %s lacks live tuning",
                type(executor).__name__,
            )
            return
        policy = build_thread_policy(self._base_config)
        executor.setMaxWorkers(policy.max_workers)
        executor.setPendingTotal(policy.max_pending_total)
        executor.setCategoryPriorities(policy.category_priorities)
        executor.setCategoryLimits(policy.category_limits)
        executor.setPendingLimits(policy.pending_limits)
        executor.setDeviceLimits(policy.device_limits)

    def _normalize_feature_request(self, features) -> tuple[str, ...]:
        """Normalize feature inputs into a tuple of unique names.

        Raises:
            TypeError: If ``features`` is not ``None``, a string, or an iterable of
                strings.
        """
        if features is None:
            return default_feature_selection()
        if isinstance(features, str):
            items = [features]
        else:
            try:
                items = list(features)
            except TypeError as exc:
                raise TypeError(
                    "features must be an iterable of strings or None"
                ) from exc
        if not items:
            return ()
        normalized: list[str] = []
        for item in items:
            if not isinstance(item, str):
                raise TypeError("feature names must be strings")
            if item not in normalized:
                normalized.append(item)
        return tuple(normalized)

    def _resolve_executor(
        self,
        supplied_executor: TaskExecutorProtocol | None,
        thread_policy: ThreadPolicy | Mapping[str, Any] | None,
    ) -> tuple[TaskExecutorProtocol, bool]:
        """Return the executor plus ownership flag for shutdown handling."""
        if supplied_executor is not None:
            return supplied_executor, False
        config_source = self._base_config
        if isinstance(thread_policy, ThreadPolicy):
            policy = thread_policy
        elif isinstance(thread_policy, Mapping):
            policy = build_thread_policy(config_source, **dict(thread_policy))
        else:
            policy = build_thread_policy(config_source)
        return self._build_executor(policy), True

    def _build_executor(self, policy: ThreadPolicy) -> TaskExecutorProtocol:
        """Construct the shared executor using the provided thread policy."""
        return QThreadPoolExecutor(policy=policy)

    def _register_executor_diagnostics(self) -> None:
        """Wire the executor metrics and retry providers into diagnostics."""
        diagnostics = self._diagnostics
        diagnostics.register_executor_providers(
            executor_accessor=lambda: self._executor,
            retry_provider=retry_diagnostics_provider,
            retry_summary_provider=retry_summary_provider,
        )

    def on_destroyed(self, _obj: Any | None = None) -> None:
        """Teardown hook to release thread pools when the widget is destroyed."""
        self._stop_headroom_monitor()
        self._shutdown_executor()

    def _shutdown_executor(self) -> None:
        """Best-effort shutdown for executors the QPaneState created."""
        if not getattr(self, "_owns_executor", False):
            return
        try:
            self._executor.shutdown(wait=False)
        except Exception:
            logger.exception("Failed to shut down QPane executor")
        finally:
            self._owns_executor = False
