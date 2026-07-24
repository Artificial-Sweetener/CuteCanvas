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
"""Configuration and installed-feature methods for the CuteCanvas facade."""

from __future__ import annotations

from cutecanvas.core.config import Config


class ConfigurationApiMixin:
    """Expose immutable settings and explicit runtime reconfiguration."""

    @property
    def settings(self) -> Config:
        """Return the active immutable configuration snapshot."""
        state = getattr(self, "_state", None)
        if state is None:
            raise AttributeError("CuteCanvas settings accessed before initialization")
        return state.settings

    @settings.setter
    def settings(self, new_settings: Config) -> None:
        """Reject direct assignment in favor of ``applySettings``."""
        del new_settings
        raise AttributeError(
            "CuteCanvas.settings is read-only; call CuteCanvas.applySettings to "
            "change configuration"
        )

    @property
    def installedFeatures(self) -> tuple[str, ...]:
        """Return feature identifiers installed on this widget."""
        return self._state.installed_features

    def applySettings(
        self, *, config: Config | None = None, **overrides: object
    ) -> None:
        """Apply a configuration snapshot or validated overrides."""
        self._state.apply_settings(config=config, **overrides)
        self.refreshMaskAutosavePolicy()
        self._apply_diagnostics_overlay_preferences()
        self._refresh_screen_tracking()
        self.markDirty()
        self.update()
