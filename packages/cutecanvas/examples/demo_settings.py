#!/usr/bin/env python3
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

"""Persist independent launch preferences and window placement for the demos."""

from __future__ import annotations

import base64
import binascii
import json
import os
from pathlib import Path

_SETTINGS_FILE = Path(__file__).resolve().parent / "demo_settings.json"
_WINDOW_SETTINGS_FILE = Path(__file__).resolve().parent / "demo_window_settings.json"


def load_demo_settings() -> dict[str, object]:
    """Load validated launcher preferences and window placement."""
    launch_data = _read_mapping(_SETTINGS_FILE)
    window_data = _read_mapping(_WINDOW_SETTINGS_FILE)
    settings: dict[str, object] = {}

    sam_enabled = launch_data.get("sam_enabled")
    if isinstance(sam_enabled, bool):
        settings["sam_enabled"] = sam_enabled
    else:
        legacy_tier = launch_data.get("tier")
        if isinstance(legacy_tier, str):
            settings["sam_enabled"] = legacy_tier == "masksam"

    _copy_string_setting(launch_data, settings, "log_level")
    _copy_string_setting(launch_data, settings, "sam_download_mode")
    _copy_optional_string_setting(launch_data, settings, "sam_model_path")
    _copy_optional_string_setting(launch_data, settings, "sam_model_url")
    _copy_optional_string_setting(launch_data, settings, "sam_model_hash")

    geometry_source = window_data if window_data else launch_data
    window_geometry = _coerce_geometry_payload(geometry_source.get("window_geometry"))
    if window_geometry is not None:
        settings["window_geometry"] = window_geometry
    window_size = _coerce_int_pair(geometry_source.get("window_size"), minimum=1)
    if window_size is not None:
        settings["window_size"] = window_size
    window_position = _coerce_int_pair(
        geometry_source.get("window_position"),
        minimum=None,
    )
    if window_position is not None:
        settings["window_position"] = window_position
    return settings


def save_demo_launch_settings(
    *,
    sam_enabled: bool,
    log_level: str,
    sam_download_mode: str,
    sam_model_path: str | None,
    sam_model_url: str | None,
    sam_model_hash: str | None,
) -> None:
    """Persist the complete launcher preference snapshot."""
    _preserve_legacy_window_settings()
    _write_mapping(
        _SETTINGS_FILE,
        {
            "sam_enabled": sam_enabled,
            "log_level": log_level,
            "sam_download_mode": sam_download_mode,
            "sam_model_path": sam_model_path,
            "sam_model_url": sam_model_url,
            "sam_model_hash": sam_model_hash,
        },
    )


def save_demo_window_settings(
    *,
    window_geometry: str | None,
    window_size: tuple[int, int],
    window_position: tuple[int, int],
) -> None:
    """Persist window placement without touching launcher preferences."""
    payload: dict[str, object] = {
        "window_size": [int(window_size[0]), int(window_size[1])],
        "window_position": [int(window_position[0]), int(window_position[1])],
    }
    if window_geometry is not None:
        payload["window_geometry"] = window_geometry
    _write_mapping(_WINDOW_SETTINGS_FILE, payload)


def _read_mapping(path: Path) -> dict[str, object]:
    """Return one JSON object or an empty mapping when unavailable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _preserve_legacy_window_settings() -> None:
    """Move legacy window placement before replacing the old combined record."""
    if _WINDOW_SETTINGS_FILE.exists():
        return
    legacy = _read_mapping(_SETTINGS_FILE)
    payload = {
        key: legacy[key]
        for key in ("window_geometry", "window_size", "window_position")
        if key in legacy
    }
    if payload:
        _write_mapping(_WINDOW_SETTINGS_FILE, payload)


def _write_mapping(path: Path, payload: dict[str, object]) -> None:
    """Atomically replace one settings record when the filesystem permits."""
    temporary_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary_path.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(path)
    except OSError:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


def _copy_string_setting(
    source: dict[str, object],
    target: dict[str, object],
    key: str,
) -> None:
    """Copy one required string-shaped setting when valid."""
    value = source.get(key)
    if isinstance(value, str):
        target[key] = value


def _copy_optional_string_setting(
    source: dict[str, object],
    target: dict[str, object],
    key: str,
) -> None:
    """Copy one nullable string-shaped setting when valid."""
    value = source.get(key)
    if value is None or isinstance(value, str):
        target[key] = value


def _coerce_int_pair(value: object, *, minimum: int | None) -> tuple[int, int] | None:
    """Return a validated integer pair from a JSON payload."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    first, second = value
    if not _is_valid_int(first) or not _is_valid_int(second):
        return None
    first = int(first)
    second = int(second)
    if minimum is not None and (first < minimum or second < minimum):
        return None
    return (first, second)


def _coerce_geometry_payload(value: object) -> str | None:
    """Return a base64 geometry payload string when valid."""
    if not isinstance(value, str) or not value:
        return None
    try:
        decoded = base64.b64decode(value.encode("ascii"), validate=True)
    except (ValueError, binascii.Error, UnicodeEncodeError):
        return None
    if not decoded:
        return None
    return value


def _is_valid_int(value: object) -> bool:
    """Return True when the value is a non-bool int."""
    return isinstance(value, int) and not isinstance(value, bool)
