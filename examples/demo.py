#!/usr/bin/env python3
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

"""Entry point for the QPane example demo application."""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if __package__ is None or __package__ == "":
    # Allow running as a script (python examples/demo.py) by adding repo root.
    sys.path.append(str(Path(__file__).resolve().parent.parent))
from examples.demo_environment import (
    DEMO_TIERS,
    DemoEnvironmentError,
    DemoEnvironmentManager,
    DemoLaunchSettings,
)
from examples.demo_settings import load_demo_settings, save_demo_settings

if TYPE_CHECKING:
    from examples.demonstration.demo_window import ExampleOptions, ExampleWindow

__all__ = ["ExampleOptions", "ExampleWindow", "main", "parse_args"]
_SAM_DOWNLOAD_MODES = ["background", "blocking", "disabled"]
_DEMO_ENVIRONMENTS = DemoEnvironmentManager(Path(__file__))


def _load_example_types() -> tuple[Any, Any]:
    """Import and cache the demo window symbols."""
    options_type = globals().get("ExampleOptions")
    window_type = globals().get("ExampleWindow")
    if options_type is None or window_type is None:
        from examples.demonstration.demo_window import (
            ExampleOptions as DemoExampleOptions,
        )
        from examples.demonstration.demo_window import (
            ExampleWindow as DemoExampleWindow,
        )

        globals()["ExampleOptions"] = DemoExampleOptions
        globals()["ExampleWindow"] = DemoExampleWindow
        options_type = DemoExampleOptions
        window_type = DemoExampleWindow
    return options_type, window_type


def __getattr__(name: str) -> Any:
    """Load demo UI types only when callers explicitly request them."""
    if name not in {"ExampleOptions", "ExampleWindow"}:
        raise AttributeError(name)
    options_type, window_type = _load_example_types()
    return options_type if name == "ExampleOptions" else window_type


def _resolve_fallback_app_data_dir() -> Path | None:
    """Return an OS-appropriate app data directory without Qt."""
    base: str | None
    if sys.platform.startswith("win"):
        base = os.getenv("APPDATA") or os.getenv("LOCALAPPDATA")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.getenv("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    if not base:
        return None
    try:
        return (Path(base) / Path(sys.executable).stem).resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _resolve_app_data_dir() -> Path | None:
    """Resolve the app data directory using Qt when available."""
    try:
        from PySide6.QtCore import QCoreApplication, QStandardPaths
    except ModuleNotFoundError:
        return _resolve_fallback_app_data_dir()
    if not QCoreApplication.applicationName():
        QCoreApplication.setApplicationName(Path(sys.executable).stem)
    app_data = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    if not app_data:
        return _resolve_fallback_app_data_dir()
    try:
        return Path(app_data).resolve()
    except (OSError, RuntimeError, ValueError):
        return _resolve_fallback_app_data_dir()


def _parse_bootstrap_args(argv: list[str]) -> argparse.Namespace:
    """Parse the CLI arguments needed for bootstrapping."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--features",
        choices=["core", "mask", "masksam"],
        default="masksam",
    )
    parser.add_argument(
        "--config-strict",
        action="store_true",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
    )
    parser.add_argument(
        "--skip-menu",
        action="store_true",
    )
    parser.add_argument(
        "--sam-download-mode",
        choices=_SAM_DOWNLOAD_MODES,
        default=None,
    )
    parser.add_argument(
        "--sam-model-path",
        default=None,
    )
    parser.add_argument(
        "--sam-model-url",
        default=None,
    )
    parser.add_argument(
        "--sam-model-hash",
        default=None,
    )
    return parser.parse_args(argv)


def _interactive_menu() -> int:
    """Present a dashboard menu to rebuild/install venvs and launch the demo."""
    tiers = ["core", "mask", "masksam"]
    log_levels = ["DEBUG", "INFO", "WARNING", "ERROR"]
    sam_modes = list(_SAM_DOWNLOAD_MODES)
    # Load defaults from disk or fall back to Mask+SAM/WARNING
    saved = load_demo_settings()
    default_tier = saved.get("tier", "masksam")
    default_level = saved.get("log_level", "WARNING")
    default_sam_mode = saved.get("sam_download_mode", "background")
    default_sam_path = saved.get("sam_model_path")
    default_sam_url = saved.get("sam_model_url")
    default_sam_hash = saved.get("sam_model_hash")
    try:
        tier_idx = tiers.index(default_tier)
    except ValueError:
        tier_idx = 2
    try:
        level_idx = log_levels.index(default_level)
    except ValueError:
        level_idx = 2
    try:
        sam_idx = sam_modes.index(default_sam_mode)
    except ValueError:
        sam_idx = 0
    state = {
        "tier_idx": tier_idx,
        "level_idx": level_idx,
        "sam_idx": sam_idx,
        "sam_model_path": default_sam_path,
        "sam_model_url": default_sam_url,
        "sam_model_hash": default_sam_hash,
        "sam_clear_checkpoint": False,
    }

    def _current_tier() -> str:
        """Return the tier name currently selected in the menu."""
        return tiers[state["tier_idx"]]

    def _resolve_sam_checkpoint_path(value: str | None) -> Path | None:
        """Resolve the SAM checkpoint path for the current menu settings."""
        normalized = value.strip() if isinstance(value, str) else ""
        if normalized:
            try:
                return Path(normalized).expanduser().resolve()
            except (OSError, RuntimeError, ValueError):
                return None
        app_data = _resolve_app_data_dir()
        if app_data is None:
            return None
        try:
            return (app_data / "mobile_sam.pt").resolve()
        except (OSError, RuntimeError, ValueError):
            return None

    def _format_optional_value(value: str | None) -> str:
        """Return a human-friendly label for optional settings values."""
        if value is None or not value.strip():
            return "(default)"
        return value

    def _build_menu_rows() -> list[dict[str, str]]:
        """Build the menu rows based on the selected feature tier."""
        rows: list[dict[str, str]] = [
            {
                "kind": "option",
                "key": "feature",
                "label": "Feature Set",
                "value": DEMO_TIERS[_current_tier()].label,
                "help": (
                    "Select feature tier. Left/Right to cycle. "
                    "(Core: Viewer, Masks: +Masks, Mask+SAM: +AI)"
                ),
            },
            {
                "kind": "option",
                "key": "log_level",
                "label": "Log Level",
                "value": log_levels[state["level_idx"]],
                "help": (
                    "Set logging verbosity. Left/Right to cycle. "
                    "(DEBUG for dev, INFO for standard)"
                ),
            },
        ]
        if _current_tier() == "masksam":
            rows.append(
                {
                    "kind": "option",
                    "key": "sam_download_mode",
                    "label": "SAM Download",
                    "value": sam_modes[state["sam_idx"]],
                    "help": (
                        "Choose SAM download mode. Left/Right to cycle. "
                        "(background, blocking, or disabled; disabled needs a checkpoint)"
                    ),
                }
            )
            rows.append(
                {
                    "kind": "input",
                    "key": "sam_model_path",
                    "label": "SAM Path",
                    "value": _format_optional_value(state["sam_model_path"]),
                    "help": (
                        "Set a local checkpoint path. Enter to edit, blank to use default."
                    ),
                }
            )
            rows.append(
                {
                    "kind": "input",
                    "key": "sam_model_url",
                    "label": "SAM URL",
                    "value": _format_optional_value(state["sam_model_url"]),
                    "help": (
                        "Set a download URL override. Enter to edit, blank to use default."
                    ),
                }
            )
            rows.append(
                {
                    "kind": "input",
                    "key": "sam_model_hash",
                    "label": "SAM Hash",
                    "value": _format_optional_value(state["sam_model_hash"]),
                    "help": (
                        "Set SHA-256 for the checkpoint. Use 'default' to force the "
                        "built-in hash, or blank to skip verification."
                    ),
                }
            )
            checkpoint_path = _resolve_sam_checkpoint_path(state["sam_model_path"])
            if checkpoint_path is not None and checkpoint_path.exists():
                rows.append(
                    {
                        "kind": "option",
                        "key": "sam_clear_checkpoint",
                        "label": "Clear SAM Checkpoint",
                        "value": "Yes" if state["sam_clear_checkpoint"] else "No",
                        "help": (
                            "Delete the resolved SAM checkpoint before launch. "
                            f"Path: {checkpoint_path}"
                        ),
                    }
                )
            else:
                state["sam_clear_checkpoint"] = False
        rows.extend(
            [
                {
                    "kind": "action",
                    "key": "run",
                    "label": "Run Demo",
                    "help": "Launch the demo application with the current settings.",
                },
                {
                    "kind": "action",
                    "key": "rebuild",
                    "label": "Rebuild Environment",
                    "help": (
                        "Recreate the virtual environment for the selected tier "
                        "(fixes dependency issues)."
                    ),
                },
                {
                    "kind": "action",
                    "key": "exit",
                    "label": "Exit",
                    "help": "Exit the launcher.",
                },
            ]
        )
        return rows

    def _clear_sam_checkpoint(path: Path) -> None:
        """Delete the resolved SAM checkpoint before launch."""
        if not path.exists():
            return
        try:
            path.unlink()
        except OSError as exc:
            print(f"\nError clearing SAM checkpoint: {exc}")
            input("Press Enter...")

    def _print_dashboard(selected_row: int, rows: list[dict[str, str]]) -> None:
        """Clear the screen and display the interactive dashboard."""
        os.system("cls" if os.name == "nt" else "clear")
        print("QPane Demo Dashboard (Arrow keys to navigate/change, Enter to select)\n")
        for idx, row in enumerate(rows):
            prefix = ">" if selected_row == idx else " "
            if row["kind"] == "option":
                print(f"{prefix} {row['label']:<16} < {row['value']} >")
            elif row["kind"] == "input":
                print(f"{prefix} {row['label']:<16} {row['value']}")
            else:
                print(f"{prefix} [ {row['label']} ]")
        print("\n")
        msg = rows[selected_row]["help"]
        # White background (47), Black text (30)
        print(f"\033[47;30m {msg:<78} \033[0m")

    def _handle_input() -> str:
        """Return action based on key press."""
        if not sys.stdin.isatty():
            return "EXIT"
        try:
            import msvcrt  # type: ignore

            ch = msvcrt.getch()
            if ch == b"\x1b":
                return "EXIT"
            if ch in {b"\r", b"\n"}:
                return "SELECT"
            if ch in {b"\x00", b"\xe0"}:
                arrow = msvcrt.getch()
                if arrow == b"H":
                    return "UP"
                if arrow == b"P":
                    return "DOWN"
                if arrow == b"K":
                    return "LEFT"
                if arrow == b"M":
                    return "RIGHT"
        except ImportError:
            return "EXIT"
        return "NONE"

    def _prompt_setting(label: str, current: str | None) -> str | None:
        """Prompt for a new setting value or clear to defaults."""
        os.system("cls" if os.name == "nt" else "clear")
        print(f"Set {label} (leave blank to use the default).\n")
        if current:
            print(f"Current: {current}")
        value = input("New value: ").strip()
        return value or None

    rows = _build_menu_rows()
    selected_row = next((idx for idx, row in enumerate(rows) if row["key"] == "run"), 0)
    while True:
        rows = _build_menu_rows()
        if selected_row >= len(rows):
            selected_row = max(len(rows) - 1, 0)
        _print_dashboard(selected_row, rows)
        action = _handle_input()
        if action == "EXIT":
            return 0
        if action == "UP":
            selected_row = (selected_row - 1) % len(rows)
        elif action == "DOWN":
            selected_row = (selected_row + 1) % len(rows)
        elif action == "LEFT":
            row = rows[selected_row]
            if row["key"] == "feature":
                state["tier_idx"] = (state["tier_idx"] - 1) % len(tiers)
            elif row["key"] == "log_level":
                state["level_idx"] = (state["level_idx"] - 1) % len(log_levels)
            elif row["key"] == "sam_download_mode":
                state["sam_idx"] = (state["sam_idx"] - 1) % len(sam_modes)
            elif row["key"] == "sam_clear_checkpoint":
                state["sam_clear_checkpoint"] = not state["sam_clear_checkpoint"]
        elif action == "RIGHT":
            row = rows[selected_row]
            if row["key"] == "feature":
                state["tier_idx"] = (state["tier_idx"] + 1) % len(tiers)
            elif row["key"] == "log_level":
                state["level_idx"] = (state["level_idx"] + 1) % len(log_levels)
            elif row["key"] == "sam_download_mode":
                state["sam_idx"] = (state["sam_idx"] + 1) % len(sam_modes)
            elif row["key"] == "sam_clear_checkpoint":
                state["sam_clear_checkpoint"] = not state["sam_clear_checkpoint"]
        elif action == "SELECT":
            row = rows[selected_row]
            if row["key"] == "run":
                tier = tiers[state["tier_idx"]]
                level = log_levels[state["level_idx"]]
                sam_mode = sam_modes[state["sam_idx"]]
                sam_path = state["sam_model_path"]
                sam_url = state["sam_model_url"]
                sam_hash = state["sam_model_hash"]
                if tier == "masksam" and state["sam_clear_checkpoint"]:
                    checkpoint_path = _resolve_sam_checkpoint_path(sam_path)
                    if checkpoint_path is not None:
                        _clear_sam_checkpoint(checkpoint_path)
                save_demo_settings(tier, level, sam_mode, sam_path, sam_url, sam_hash)
                try:
                    _DEMO_ENVIRONMENTS.ensure_ready(tier)
                    return _DEMO_ENVIRONMENTS.launch(
                        tier,
                        DemoLaunchSettings(
                            log_level=level,
                            sam_download_mode=sam_mode,
                            sam_model_path=sam_path,
                            sam_model_url=sam_url,
                            sam_model_hash=sam_hash,
                        ),
                    )
                except (
                    DemoEnvironmentError,
                    OSError,
                    subprocess.CalledProcessError,
                ) as exc:
                    print(f"\nError: {exc}")
                    input("Press Enter...")
            elif row["key"] == "rebuild":
                tier = tiers[state["tier_idx"]]
                level = log_levels[state["level_idx"]]
                sam_mode = sam_modes[state["sam_idx"]]
                sam_path = state["sam_model_path"]
                sam_url = state["sam_model_url"]
                sam_hash = state["sam_model_hash"]
                save_demo_settings(tier, level, sam_mode, sam_path, sam_url, sam_hash)
                try:
                    print(f"\nRebuilding {tier} environment...")
                    _DEMO_ENVIRONMENTS.ensure_ready(tier, rebuild=True)
                    print("Done.")
                    input("Press Enter...")
                except (
                    DemoEnvironmentError,
                    OSError,
                    subprocess.CalledProcessError,
                ) as exc:
                    print(f"\nError: {exc}")
                    input("Press Enter...")
            elif row["key"] == "exit":
                tier = tiers[state["tier_idx"]]
                level = log_levels[state["level_idx"]]
                sam_mode = sam_modes[state["sam_idx"]]
                sam_path = state["sam_model_path"]
                sam_url = state["sam_model_url"]
                sam_hash = state["sam_model_hash"]
                save_demo_settings(tier, level, sam_mode, sam_path, sam_url, sam_hash)
                return 0
            elif row["key"] == "sam_model_path":
                state["sam_model_path"] = _prompt_setting(
                    "SAM model path", state["sam_model_path"]
                )
            elif row["key"] == "sam_model_url":
                state["sam_model_url"] = _prompt_setting(
                    "SAM model URL", state["sam_model_url"]
                )
            elif row["key"] == "sam_model_hash":
                state["sam_model_hash"] = _prompt_setting(
                    "SAM model hash", state["sam_model_hash"]
                )


def parse_args(argv: Iterable[str] | None = None) -> ExampleOptions:
    """Parse CLI arguments controlling feature selection and config strictness."""
    options_type, _window_type = _load_example_types()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--features",
        choices=["core", "mask", "masksam"],
        default="masksam",
        help="Select example feature set (core viewer, mask tools, or Mask+SAM).",
    )
    parser.add_argument(
        "--config-strict",
        action="store_true",
        help="Raise errors when presets override config namespaces for inactive features.",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Set the logging verbosity level.",
    )
    parser.add_argument(
        "--skip-menu",
        action="store_true",
        help="Bypass the interactive menu (used by the launcher).",
    )
    parser.add_argument(
        "--sam-download-mode",
        choices=_SAM_DOWNLOAD_MODES,
        default=None,
        help=(
            "Choose how SAM checkpoints are acquired "
            "(background, blocking, or disabled)."
        ),
    )
    parser.add_argument(
        "--sam-model-path",
        default=None,
        help="Override the local SAM checkpoint path for Mask+SAM demos.",
    )
    parser.add_argument(
        "--sam-model-url",
        default=None,
        help="Override the SAM checkpoint download URL for Mask+SAM demos.",
    )
    parser.add_argument(
        "--sam-model-hash",
        default=None,
        help=(
            "Provide a SHA-256 checksum for the SAM checkpoint. "
            "Use 'default' to request the built-in MobileSAM hash."
        ),
    )
    ns = parser.parse_args(list(argv) if argv is not None else None)
    return options_type(
        feature_set=ns.features,
        config_strict=bool(ns.config_strict),
        log_level=ns.log_level,
        sam_download_mode=ns.sam_download_mode,
        sam_model_path=ns.sam_model_path,
        sam_model_url=ns.sam_model_url,
        sam_model_hash=ns.sam_model_hash,
    )


def _configure_logging(level_name: str = "INFO") -> None:
    """Ensure example logging emits messages to the console at the requested level."""
    root = logging.getLogger()
    level = getattr(logging, level_name.upper())
    if root.handlers:
        root.setLevel(level)
        return
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
    )


def main(argv: Iterable[str] | None = None) -> int:
    """Entry point for launching the example application."""
    args = list(argv) if argv is not None else sys.argv[1:]
    if not args:
        return _interactive_menu()
    bootstrap = _parse_bootstrap_args(args)
    if not _DEMO_ENVIRONMENTS.is_current_process(bootstrap.features):
        try:
            _DEMO_ENVIRONMENTS.ensure_ready(bootstrap.features)
        except (
            DemoEnvironmentError,
            OSError,
            subprocess.CalledProcessError,
        ) as exc:
            print(f"\nError: {exc}")
            return 1
        return _DEMO_ENVIRONMENTS.launch(
            bootstrap.features,
            DemoLaunchSettings(
                log_level=bootstrap.log_level,
                config_strict=bootstrap.config_strict,
                sam_download_mode=bootstrap.sam_download_mode,
                sam_model_path=bootstrap.sam_model_path,
                sam_model_url=bootstrap.sam_model_url,
                sam_model_hash=bootstrap.sam_model_hash,
            ),
        )
    _options_type, window_type = _load_example_types()
    from PySide6.QtGui import QImageReader
    from PySide6.QtWidgets import QApplication

    from qpane import Config

    opts = parse_args(args)
    _configure_logging(opts.log_level)
    app = QApplication(sys.argv[:1])
    QImageReader.setAllocationLimit(0)
    config = Config()
    if opts.feature_set == "masksam":
        sam_overrides: dict[str, object] = {}
        if opts.sam_download_mode:
            sam_overrides["sam_download_mode"] = opts.sam_download_mode
        if opts.sam_model_path:
            sam_overrides["sam_model_path"] = opts.sam_model_path
        if opts.sam_model_url:
            sam_overrides["sam_model_url"] = opts.sam_model_url
        if opts.sam_model_hash:
            sam_overrides["sam_model_hash"] = opts.sam_model_hash
        if sam_overrides:
            config.configure(**sam_overrides)
    window = window_type(opts, config=config)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
