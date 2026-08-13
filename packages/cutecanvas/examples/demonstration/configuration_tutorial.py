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
"""Teach live configuration and diagnostics as one host-owned workflow.

The editor widget owns runtime behavior; this controller owns the example's
configuration dialog, persistence snapshot, and matching menu actions. Keeping
those responsibilities together shows embedders how to avoid a second mutable
configuration model in their application shell.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from functools import partial

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QDialog, QMenu, QWidget

from cutecanvas import Config, CuteCanvas
from demonstration.config.dialog import ConfigDialog

DIAGNOSTIC_DOMAIN_FIELD = "diagnostics_domains_enabled"
SAM_CONFIG_FIELDS = ConfigDialog.SAM_FIELDS

_DETAIL_LABELS = {
    "cache": "Cache",
    "swap": "Swap",
    "mask": "Mask",
    "executor": "Executor",
    "retry": "Retry",
    "sam": "SAM",
}


class ConfigurationTutorialController:
    """Own the demo's settings dialog and diagnostics-menu synchronization."""

    def __init__(
        self,
        canvas: CuteCanvas,
        parent: QWidget,
        config: Config,
        *,
        active_features: Sequence[str],
        dialog_fields: set[str],
        set_status: Callable[[str], None],
        refresh_tools: Callable[[], None],
    ) -> None:
        """Retain the public editor, config value, and narrow host callbacks."""
        self._canvas = canvas
        self._parent = parent
        self._config = config
        self._active_features = tuple(active_features)
        self._dialog_fields = set(dialog_fields)
        self._set_status = set_status
        self._refresh_tools = refresh_tools
        self._overlay_enabled = canvas.diagnosticsOverlayEnabled()
        self._overlay_toggle_action: QAction | None = None
        self._detail_actions: dict[str, QAction] = {}

    @property
    def detail_actions(self) -> Mapping[str, QAction]:
        """Return the diagnostics-domain actions for host inspection."""
        return dict(self._detail_actions)

    def open_dialog(self) -> None:
        """Open the settings dialog and apply an accepted result."""
        dialog = ConfigDialog(
            self._config,
            self._parent,
            active_features=self._active_features,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        result = dialog.result()
        if result.values:
            self.apply_configuration(
                result.values,
                config_fields=result.config_fields,
                restart_fields=result.restart_fields,
            )

    def apply_configuration(
        self,
        values: dict[str, object],
        *,
        config_fields: set[str],
        restart_fields: set[str] | None = None,
    ) -> None:
        """Apply live settings and retain restart-only SAM changes."""
        config_snapshot = self._config.as_dict()
        config_updates = {
            key: value
            for key, value in values.items()
            if key in config_fields or key in config_snapshot
        }
        restart_fields = set(restart_fields or ())
        live_updates = {
            key: value
            for key, value in config_updates.items()
            if key not in restart_fields
        }
        deferred_updates = {
            key: value for key, value in config_updates.items() if key in restart_fields
        }
        live_config = self._config.copy()
        if live_updates:
            collapsed_live = ConfigDialog.collapse_values(live_updates)
            live_config.configure(**collapsed_live)
            self._config.configure(**collapsed_live)
        if deferred_updates:
            self._config.configure(**ConfigDialog.collapse_values(deferred_updates))
        self.apply_detail_preferences(values)
        target_overlay = bool(
            values.get(
                "diagnostics_overlay_enabled",
                config_snapshot.get(
                    "diagnostics_overlay_enabled",
                    self._overlay_enabled,
                ),
            )
        )
        self._apply_live_settings(
            live_updates,
            overlay_target=target_overlay,
            config_fields=config_fields,
            config_override=live_config,
            preconfigured=True,
        )
        if any(name in SAM_CONFIG_FIELDS for name in live_updates):
            success, message = self._canvas.refreshSamFeature()
            if not success:
                self._set_status(message)
        if deferred_updates:
            self._announce_sam_restart_required(deferred_updates)
        else:
            self._set_status("Configuration applied.")

    def apply_detail_preferences(self, values: dict[str, object]) -> None:
        """Apply configured diagnostics domains through the public facade."""
        if DIAGNOSTIC_DOMAIN_FIELD not in self._dialog_fields:
            self._detail_actions.clear()
            self._refresh_detail_enabled()
            return
        available_domains = set(self._canvas.diagnosticsDomains())
        config_snapshot = self._config.as_dict()
        configured = values.get(
            DIAGNOSTIC_DOMAIN_FIELD,
            config_snapshot.get(DIAGNOSTIC_DOMAIN_FIELD, ()),
        )
        target_domains = tuple(
            domain
            for domain in self._ordered_domains(configured)  # type: ignore[arg-type]
            if domain in available_domains
        )
        for domain in available_domains:
            self._canvas.setDiagnosticsDomainEnabled(
                domain,
                domain in target_domains,
            )
        self._sync_detail_actions()

    def build_diagnostics_menu(self, menu: QMenu) -> None:
        """Populate one menu from the editor's advertised diagnostics domains."""
        menu.clear()
        toggle = QAction("Enable Overlay", self._parent, checkable=True)
        toggle.setChecked(self._overlay_enabled)
        toggle.toggled.connect(self._handle_overlay_toggled)
        self._overlay_toggle_action = toggle
        menu.addAction(toggle)
        menu.addSeparator()
        self._detail_actions.clear()
        if DIAGNOSTIC_DOMAIN_FIELD in self._dialog_fields:
            for domain in self._canvas.diagnosticsDomains():
                action = QAction(
                    _DETAIL_LABELS.get(domain, domain.title()),
                    self._parent,
                    checkable=True,
                )
                action.setChecked(self._canvas.diagnosticsDomainEnabled(domain))
                action.toggled.connect(partial(self._handle_detail_toggled, domain))
                menu.addAction(action)
                self._detail_actions[domain] = action
        self._refresh_detail_enabled()

    def sync_overlay_toggle(self, enabled: bool) -> None:
        """Mirror an overlay state change emitted by CuteCanvas."""
        previous = self._overlay_enabled
        if previous == enabled:
            return
        self._overlay_enabled = enabled
        self._config.configure(diagnostics_overlay_enabled=enabled)
        self._set_action_checked(self._overlay_toggle_action, enabled)
        self._refresh_detail_enabled()
        self._set_status(
            "Diagnostics overlay enabled." if enabled else "Diagnostics overlay hidden."
        )

    def sync_detail_toggle(self, domain: str, enabled: bool) -> None:
        """Mirror one diagnostics-domain state change emitted by CuteCanvas."""
        if DIAGNOSTIC_DOMAIN_FIELD not in self._dialog_fields:
            return
        snapshot = self._config.as_dict()
        configured = list(snapshot.get(DIAGNOSTIC_DOMAIN_FIELD, ()) or ())
        if enabled and domain not in configured:
            configured.append(domain)
        elif not enabled and domain in configured:
            configured = [item for item in configured if item != domain]
        ordered = self._ordered_domains(configured)
        if tuple(snapshot.get(DIAGNOSTIC_DOMAIN_FIELD, ())) != ordered:
            self._config.configure(**{DIAGNOSTIC_DOMAIN_FIELD: ordered})
        self._set_action_checked(self._detail_actions.get(domain), enabled)
        self._refresh_detail_enabled()

    def _apply_live_settings(
        self,
        values: dict[str, object],
        overlay_target: bool | None = None,
        *,
        config_fields: set[str],
        config_override: Config | None = None,
        preconfigured: bool = False,
    ) -> None:
        """Apply supported live fields without rebuilding the editor widget."""
        config_snapshot = self._config.as_dict()
        live_updates = {
            key: value
            for key, value in values.items()
            if key in config_fields or key in config_snapshot
        }
        if live_updates and not preconfigured:
            target_config = config_override or self._config
            target_config.configure(**ConfigDialog.collapse_values(live_updates))
        apply_config = config_override or self._config
        if live_updates:
            self._canvas.applySettings(config=apply_config)
            self._refresh_tools()
        if overlay_target is None:
            overlay_target = bool(
                values.get(
                    "diagnostics_overlay_enabled",
                    config_snapshot.get("diagnostics_overlay_enabled", False),
                )
            )
        self._apply_overlay_setting(overlay_target, announce=True)

    def _announce_sam_restart_required(
        self,
        deferred_updates: dict[str, object],
    ) -> None:
        """Explain why restart-only SAM checkpoint changes remain pending."""
        if any(name in SAM_CONFIG_FIELDS for name in deferred_updates):
            self._set_status(
                "SAM checkpoint changes queued. Restart the demo to apply "
                "blocking/disabled settings."
            )

    def _apply_overlay_setting(self, enabled: bool, *, announce: bool) -> None:
        """Apply overlay state to config, widget, and matching actions."""
        previous = self._overlay_enabled
        self._overlay_enabled = enabled
        self._config.configure(diagnostics_overlay_enabled=enabled)
        self._canvas.setDiagnosticsOverlayEnabled(enabled)
        self._set_action_checked(self._overlay_toggle_action, enabled)
        self._refresh_detail_enabled()
        if announce and previous != enabled:
            self._set_status(
                "Diagnostics overlay enabled."
                if enabled
                else "Diagnostics overlay hidden."
            )

    def _handle_overlay_toggled(self, checked: bool) -> None:
        """Apply a user-requested overlay visibility change."""
        self._apply_overlay_setting(checked, announce=True)

    def _handle_detail_toggled(self, domain: str, checked: bool) -> None:
        """Persist and apply one user-requested diagnostics-domain change."""
        snapshot = self._config.as_dict()
        configured = set(snapshot.get(DIAGNOSTIC_DOMAIN_FIELD, ()) or ())
        if checked:
            configured.add(domain)
        else:
            configured.discard(domain)
        ordered = self._ordered_domains(configured)
        self._config.configure(**{DIAGNOSTIC_DOMAIN_FIELD: ordered})
        self.apply_detail_preferences({DIAGNOSTIC_DOMAIN_FIELD: ordered})

    def _ordered_domains(self, domains: Sequence[str]) -> tuple[str, ...]:
        """Order enabled domains exactly as the public facade advertises them."""
        requested = set(domains)
        return tuple(
            domain
            for domain in self._canvas.diagnosticsDomains()
            if domain in requested
        )

    def _refresh_detail_enabled(self) -> None:
        """Disable detail actions while their overlay is hidden."""
        for action in self._detail_actions.values():
            action.setEnabled(self._overlay_enabled)

    def _sync_detail_actions(self) -> None:
        """Align each detail action with the authoritative widget state."""
        for domain, action in self._detail_actions.items():
            self._set_action_checked(
                action,
                self._canvas.diagnosticsDomainEnabled(domain),
            )
        self._refresh_detail_enabled()

    @staticmethod
    def _set_action_checked(action: QAction | None, checked: bool) -> None:
        """Change one check state without re-entering its user handler."""
        if action is None or action.isChecked() == checked:
            return
        blocked = action.blockSignals(True)
        action.setChecked(checked)
        action.blockSignals(blocked)
