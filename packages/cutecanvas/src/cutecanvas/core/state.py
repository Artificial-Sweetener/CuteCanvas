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

"""Configuration, feature, cache, and diagnostics state for CuteCanvas."""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from qpane.sdk.cache import CacheCoordinator, CacheRegistry
from qpane.sdk.configuration import (
    CacheSettings,
    FeatureAwareConfig,
    FeatureConfigDescriptor,
    diff_config_fields,
)
from qpane.sdk.diagnostics import (
    Diagnostics,
    DiagnosticsProvider,
    DiagnosticsRegistry,
    DiagnosticsSnapshot,
)
from qpane.sdk.execution import (
    ExecutionRuntime,
    ExecutionScope,
    retry_detail_records,
    retry_summary_records,
)
from qpane.sdk.types import DiagnosticRecord

from ..runtime.headroom_monitor import HeadroomMonitor
from .config import Config
from .config_features import iter_descriptors
from .fallbacks import FeatureFailure, FeatureFallbacks
from .feature_coordinator import FeatureCoordinator, default_feature_selection

if TYPE_CHECKING:  # pragma: no cover

    from ..canvas import CuteCanvas
MB = 1024 * 1024


logger = logging.getLogger(__name__)


def _canvas_view(canvas: CuteCanvas):
    """Return ``qpane.view()`` while tolerating partially-initialized panes."""
    try:
        return canvas.view()
    except AttributeError:
        return None


class CuteCanvasState:
    """Own CuteCanvas configuration, features, caches, and diagnostics."""

    def __init__(
        self,
        *,
        qpane: CuteCanvas,
        initial_config: Config | None,
        config_overrides: Mapping[str, Any] | None,
        features: Iterable[str] | None,
        execution_runtime: ExecutionRuntime,
        execution_scope: ExecutionScope,
        config_strict: bool = False,
    ) -> None:
        """Capture configuration, features, caches, and diagnostics.

        Args:
            qpane: Owning QPane facade whose collaborators are configured by this
                state container.
            initial_config: Optional baseline :class:`Config` snapshot to start
                from instead of the global singleton.
            config_overrides: Mapping of config keys applied on top of the base.
            features: Optional iterable of feature names requested by the host.
            execution_runtime: Runtime supplying diagnostics and editor execution.
            execution_scope: Canvas-owned root for state services.
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
        self._cache_coordinator: CacheCoordinator | None = None
        self._cache_registry: CacheRegistry | None = None
        self._diagnostics = Diagnostics(qpane)
        self._diagnostics.register_core_providers(lambda: _canvas_view(qpane))
        self._execution_runtime = execution_runtime
        self._register_execution_diagnostics()
        self._execution_subscription = execution_runtime.subscribe_diagnostics(
            lambda _snapshots: self._diagnostics.set_dirty("executor")
        )
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
        self._headroom = HeadroomMonitor(
            owner=qpane,
            execution_scope=execution_scope,
            coordinator=lambda: self._cache_coordinator,
            settings=self._cache_settings,
        )

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
            Pushes configuration into rendering, masks, and cache coordination.
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
        self.apply_cache_settings()
        self._headroom.restart()

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

        def _provider(_qpane: CuteCanvas) -> tuple[DiagnosticRecord, ...]:
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
        overrides = cache_settings.explicit_overrides_mb()
        weights = cache_settings.weights.normalized(
            {"tiles", "pyramids", "mask_overlays", "models"}
        )
        resolved_budgets = cache_settings.resolve_consumer_budgets_bytes(
            active_budget_bytes,
            active_consumers={"tiles", "pyramids", "mask_overlays", "models"},
        )
        for consumer_id in ("tiles", "pyramids", "mask_overlays", "models"):
            if not coordinator.has_consumer(consumer_id):
                continue
            override_mb = overrides.get(consumer_id)
            coordinator.set_consumer_override(
                consumer_id,
                None if override_mb is None else override_mb * MB,
            )
            weight = weights.get(consumer_id, 0.0)
            coordinator.set_consumer_weight(consumer_id, weight)
            budget_bytes = resolved_budgets.get(consumer_id)
            if budget_bytes is not None:
                coordinator.set_consumer_preferred(consumer_id, budget_bytes)

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
        self._headroom.restart()
        return coordinator

    def _cache_settings(self) -> CacheSettings:
        """Return the active :class:`CacheSettings`, defaulting to an empty struct."""
        cache_settings = getattr(self._base_config, "cache", None)
        if isinstance(cache_settings, CacheSettings):
            return cache_settings
        return CacheSettings()

    def _resolve_view_collaborators(
        self,
    ) -> tuple[object | None, object | None, object | None, object | None]:
        """Return view, presenter, viewport, and tile manager via the facade."""
        try:
            view = self._qpane.view()
        except AttributeError:
            if not self._missing_view_logged:
                logger.warning(
                    "Skipping settings application because the view is unavailable"
                )
                self._missing_view_logged = True
            return None, None, None, None
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
        return view, presenter, viewport, tile_manager

    def _apply_settings_to_components(self, old_settings: FeatureAwareConfig) -> None:
        """Push updated settings to collaborators and refresh default brush size when used."""
        qpane = self._qpane
        (
            _view,
            _presenter,
            viewport,
            tile_manager,
        ) = self._resolve_view_collaborators()
        if viewport is not None:
            viewport.applyConfig(self.settings)
        if tile_manager is not None:
            tile_manager.apply_config(self.settings)
        masks = qpane._masks_controller
        masks.apply_config(self.settings)
        if qpane.interaction.brush_size == old_settings.default_brush_size:
            qpane.interaction.brush_size = self.settings.default_brush_size

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

    def _register_execution_diagnostics(self) -> None:
        """Wire runtime and retry snapshots into diagnostics."""
        diagnostics = self._diagnostics
        diagnostics.register_execution_providers(
            execution_accessor=self._execution_runtime.execution_snapshots,
            retry_provider=lambda _canvas: retry_detail_records(self._retry_managers()),
            retry_summary_provider=lambda _canvas: retry_summary_records(
                self._retry_managers()
            ),
        )

    def _retry_managers(self) -> Mapping[str, object | None]:
        """Return renderer and editor retry owners in display order."""
        canvas = self._qpane
        view = canvas.view()
        return {
            "tiles": getattr(view, "tile_manager", None),
            "pyramid": view.pyramid_manager,
            "autosave": canvas.autosaveManager(),
            "sam": canvas.samManager(),
        }

    def on_destroyed(self, _obj: Any | None = None) -> None:
        """Close feature-native services before the canvas execution scope."""
        manager = self._qpane.samManager()
        if manager is not None:
            finalizer = manager.shutdown()
            if finalizer is not None:
                self._qpane._execution_binding.defer_close_until(finalizer)
        self._execution_subscription.close()
        try:
            self._headroom.close()
        except Exception:
            logger.exception("Failed to close cache headroom monitoring")
