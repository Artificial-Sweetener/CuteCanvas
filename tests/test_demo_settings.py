#    QPane + CuteCanvas - High-performance PySide6 rendering and editing
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

"""Verify durable and independently owned demo preferences."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

from examples import cutecanvas_demo, demo_settings


def test_window_placement_cannot_overwrite_launcher_preferences(
    monkeypatch,
    tmp_path,
) -> None:
    """Keep the selected SAM preference stable across geometry writes."""
    monkeypatch.setattr(demo_settings, "_SETTINGS_FILE", tmp_path / "launch.json")
    monkeypatch.setattr(
        demo_settings,
        "_WINDOW_SETTINGS_FILE",
        tmp_path / "window.json",
    )

    demo_settings.save_demo_launch_settings(
        sam_enabled=True,
        log_level="DEBUG",
        sam_download_mode="disabled",
        sam_model_path="C:/models/mobile_sam.pt",
        sam_model_url=None,
        sam_model_hash="abc",
    )
    demo_settings.save_demo_window_settings(
        window_geometry=None,
        window_size=(1280, 900),
        window_position=(24, 48),
    )

    saved = demo_settings.load_demo_settings()
    assert saved["sam_enabled"] is True
    assert saved["log_level"] == "DEBUG"
    assert saved["window_size"] == (1280, 900)
    assert saved["window_position"] == (24, 48)


def test_existing_launcher_choice_survives_the_settings_split(
    monkeypatch,
    tmp_path,
) -> None:
    """Preserve the prior SAM choice and window placement during migration."""
    launch_path = tmp_path / "launch.json"
    window_path = tmp_path / "window.json"
    launch_path.write_text(
        json.dumps(
            {
                "tier": "mask",
                "log_level": "INFO",
                "sam_download_mode": "background",
                "sam_model_path": None,
                "sam_model_url": None,
                "window_size": [1100, 700],
                "window_position": [10, 20],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(demo_settings, "_SETTINGS_FILE", launch_path)
    monkeypatch.setattr(demo_settings, "_WINDOW_SETTINGS_FILE", window_path)

    assert demo_settings.load_demo_settings()["sam_enabled"] is False
    demo_settings.save_demo_launch_settings(
        sam_enabled=False,
        log_level="INFO",
        sam_download_mode="background",
        sam_model_path=None,
        sam_model_url=None,
        sam_model_hash=None,
    )

    saved = demo_settings.load_demo_settings()
    assert saved["sam_enabled"] is False
    assert saved["window_size"] == (1100, 700)
    assert saved["window_position"] == (10, 20)


def test_launcher_saves_a_changed_sam_choice_before_escape(monkeypatch) -> None:
    """Persist a changed launcher choice without requiring a demo launch."""
    saved_preferences: list[dict[str, object]] = []
    key_presses = iter(
        (
            b"\xe0",
            b"H",
            b"\xe0",
            b"H",
            b"\xe0",
            b"M",
            b"\x1b",
        )
    )

    monkeypatch.setattr(
        cutecanvas_demo,
        "load_demo_settings",
        lambda: {
            "sam_enabled": False,
            "log_level": "WARNING",
            "sam_download_mode": "background",
            "sam_model_path": None,
            "sam_model_url": None,
            "sam_model_hash": None,
        },
    )
    monkeypatch.setattr(
        cutecanvas_demo,
        "save_demo_launch_settings",
        lambda **values: saved_preferences.append(values),
    )
    monkeypatch.setattr(cutecanvas_demo.os, "system", lambda _command: 0)
    monkeypatch.setattr(
        cutecanvas_demo.sys,
        "stdin",
        SimpleNamespace(isatty=lambda: True),
    )
    monkeypatch.setitem(
        sys.modules,
        "msvcrt",
        SimpleNamespace(getch=lambda: next(key_presses)),
    )

    assert cutecanvas_demo._interactive_menu() == 0
    assert saved_preferences[-1]["sam_enabled"] is True
