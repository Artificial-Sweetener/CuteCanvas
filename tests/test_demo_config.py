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

"""Example configuration dialog integration and persistence tests."""

import pytest
from cutecanvas import Config, CuteCanvas
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QCheckBox
from qpane.features.registry import FeatureInstallError

from examples.cutecanvas_demo import ExampleOptions, ExampleWindow, parse_args
from examples.demonstration.config.dialog import ConfigDialog, DomainCheckboxGroup
from examples.demonstration.config.spec import (
    build_sections_for_features,
    field_sets_for_sections,
)
from tests.helpers.render_plan import make_render_plan

MB = 1024 * 1024


def test_live_config_applies_without_rebuild(qapp):
    """Live dialog updates apply without rebuilding the CuteCanvas."""
    demo_config = Config()
    demo_config.cache.mode = "hard"
    demo_config.cache.budget_mb = 1024
    window = ExampleWindow(ExampleOptions(), config=demo_config)
    try:
        sections = build_sections_for_features(window._active_features)
        _, config_fields, _ = field_sets_for_sections(sections)
        old_qpane = window.qpane
        cache_settings = old_qpane.settings.cache
        budgets_bytes = cache_settings.resolved_consumer_budgets_bytes()
        budgets = {key: int(value // MB) for key, value in budgets_bytes.items()}
        overrides = {
            "cache.tiles.mb": budgets.get("tiles", 0) + 128,
        }
        if "cache.extensions.mask_overlays.mb" in config_fields:
            overrides["cache.extensions.mask_overlays.mb"] = (
                budgets.get("mask_overlays", 0) + 64
            )
        if "cache.extensions.models.mb" in config_fields:
            overrides["cache.extensions.models.mb"] = budgets.get("models", 0) + 32
        window.configuration.apply_configuration(
            overrides,
            config_fields=config_fields,
        )
        assert window.qpane is old_qpane
        cache_settings = window.qpane.settings.cache
        assert cache_settings.override_mb("tiles") == overrides["cache.tiles.mb"]
        if "cache.extensions.mask_overlays.mb" in config_fields:
            assert (
                cache_settings.override_mb("mask_overlays")
                == overrides["cache.extensions.mask_overlays.mb"]
            )
        else:
            assert cache_settings.override_mb("mask_overlays") is None
        if "cache.extensions.models.mb" in config_fields:
            assert (
                cache_settings.override_mb("models")
                == overrides["cache.extensions.models.mb"]
            )
        else:
            assert cache_settings.override_mb("models") is None
        demo_cache = demo_config.cache
        assert demo_cache.override_mb("tiles") == overrides["cache.tiles.mb"]
        if "cache.extensions.mask_overlays.mb" in config_fields:
            assert (
                demo_cache.override_mb("mask_overlays")
                == overrides["cache.extensions.mask_overlays.mb"]
            )
        else:
            assert demo_cache.override_mb("mask_overlays") is None
        if "cache.extensions.models.mb" in config_fields:
            assert (
                demo_cache.override_mb("models")
                == overrides["cache.extensions.models.mb"]
            )
        else:
            assert demo_cache.override_mb("models") is None
        expected_bytes = cache_settings.resolve_active_budget_bytes()
        coordinator = window.qpane.cacheCoordinator
        assert coordinator is not None
        assert coordinator.active_budget_bytes == expected_bytes
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_diagnostics_include_pyramid_level(qapp):
    qpane_widget = CuteCanvas(features=())
    try:
        qpane_widget.resize(400, 400)
        base_image = QImage(2048, 2048, QImage.Format_ARGB32)
        base_image.fill(0)
        qpane_widget.original_image = base_image
        view = qpane_widget.view()
        render_plan = make_render_plan(
            qpane_widget.rect(),
            source_image=QImage(512, 512, QImage.Format_ARGB32),
            pyramid_scale=0.25,
            tile_size=view.tile_manager.tile_size,
            tile_overlap=view.tile_manager.tile_overlap,
            max_tile_cols=0,
            max_tile_rows=0,
            physical_viewport_rect=qpane_widget.physicalViewportRect(),
        )
        view.renderer._current_render_plan = render_plan
        snapshot = qpane_widget.gatherDiagnostics()
        assert any(
            record.label == "Pyramid Level"
            and "512px" in record.value
            and "0.250x" in record.value
            for record in snapshot.records
        )
    finally:
        qpane_widget.deleteLater()
        qapp.processEvents()


def test_config_dialog_preview_tracks_changes(qapp):
    dialog = ConfigDialog(Config())
    try:
        widget = dialog._widgets["mask_prefetch_enabled"]
        widget.setChecked(False)
        dialog._update_preview()
        assert dialog._preview_text.toPlainText()
        assert "mask_prefetch_enabled" in dialog._preview_text.toPlainText()
        widget.setChecked(True)
        dialog._update_preview()
        assert dialog._preview_status_label.text() == "No changes yet"
    finally:
        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()


def test_config_dialog_sam_restart_guidance(qapp):
    dialog = ConfigDialog(Config(), active_features=("mask", "sam"))
    try:
        mode_widget = dialog._widgets["sam_download_mode"]
        path_widget = dialog._widgets["sam_model_path"]
        mode_widget.setCurrentText("blocking")
        path_widget.setText("C:/tmp/mobile_sam.pt")
        dialog._update_preview()
        assert "Restart required" in dialog._preview_status_label.text()
        result = dialog.result()
        assert "sam_download_mode" in result.restart_fields
    finally:
        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()


def test_config_dialog_sam_background_applies_live(qapp):
    dialog = ConfigDialog(Config(), active_features=("mask", "sam"))
    try:
        path_widget = dialog._widgets["sam_model_path"]
        path_widget.setText("C:/tmp/mobile_sam.pt")
        dialog._update_preview()
        assert dialog._preview_status_label.text() == "Applies live"
        result = dialog.result()
        assert not result.restart_fields
    finally:
        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()


def test_config_dialog_filter_hides_sections(qapp):
    dialog = ConfigDialog(Config())
    try:
        dialog._filter_input.setText("mask")
        qapp.processEvents()
        assert not dialog._section_items["Masks"].isHidden()
        assert dialog._section_items["Viewer"].isHidden()
        dialog._filter_input.setText("zzzz")
        qapp.processEvents()
        assert dialog._no_matches_label.isVisible()
    finally:
        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()


def test_config_dialog_exposes_zoom_normalization_toggles(qapp):
    dialog = ConfigDialog(Config())
    try:
        widget = dialog._widgets.get("normalize_zoom_on_screen_change")
        assert isinstance(widget, QCheckBox)
        widget.setChecked(True)
        one_to_one_widget = dialog._widgets.get("normalize_zoom_for_one_to_one")
        assert isinstance(one_to_one_widget, QCheckBox)
        one_to_one_widget.setChecked(True)
        result = dialog.result()
        assert result.values["normalize_zoom_on_screen_change"] is True
        assert result.values["normalize_zoom_for_one_to_one"] is True
    finally:
        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()


def test_config_dialog_hides_mask_fields_without_feature(qapp):
    dialog = ConfigDialog(Config(), active_features=())
    try:
        assert "Masks" not in dialog._section_items
        assert "SAM" not in dialog._section_items
        assert "mask_prefetch_enabled" not in dialog._widgets
        assert "mask_autosave_enabled" not in dialog._widgets
    finally:
        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()


def test_config_dialog_hides_sam_fields_when_mask_only(qapp):
    dialog = ConfigDialog(Config(), active_features=("mask",))
    try:
        domains_widget = dialog._widgets.get("diagnostics_domains_enabled")
        assert isinstance(domains_widget, DomainCheckboxGroup)
        assert "sam" not in domains_widget.domains()
        assert "cache.weights.extensions.models" not in dialog._widgets
        assert "cache.prefetch.extensions.source_warmup" not in dialog._widgets
        assert "sam_download_mode" not in dialog._widgets
        assert "sam_model_path" not in dialog._widgets
        assert "sam_model_url" not in dialog._widgets
        assert "sam_model_hash" not in dialog._widgets
    finally:
        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()


def test_config_dialog_toggles_cache_mode_fields(qapp):
    dialog = ConfigDialog(Config(), active_features=())
    try:
        dialog.show()
        qapp.processEvents()
        mode = dialog._cache_mode
        assert mode is not None
        headroom_percent = dialog._field_containers.get("cache.headroom_percent")
        headroom_cap = dialog._field_containers.get("cache.headroom_cap_mb")
        budget = dialog._field_containers.get("cache.budget_mb")
        assert headroom_percent is not None
        assert headroom_cap is not None
        assert budget is not None
        mode.setCurrentText("hard")
        qapp.processEvents()
        assert budget.isVisible()
        assert not headroom_percent.isVisible()
        assert not headroom_cap.isVisible()
        mode.setCurrentText("auto")
        qapp.processEvents()
        assert headroom_percent.isVisible()
        assert headroom_cap.isVisible()
        assert not budget.isVisible()
    finally:
        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()


def test_parse_args_enables_config_strict() -> None:
    opts = parse_args(["--config-strict"])
    assert opts.sam_enabled is False
    assert opts.config_strict is True


def test_demo_window_includes_masks_under_config_strict(qapp):
    demo_config = Config()
    demo_config.mask_border_enabled = True
    window = ExampleWindow(ExampleOptions(config_strict=True), config=demo_config)
    try:
        assert window.qpane.maskFeatureAvailable()
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_diagnostics_menu_excludes_sam_when_disabled(qapp):
    demo_config = Config()
    window = ExampleWindow(ExampleOptions(), config=demo_config)
    try:
        assert "sam" not in window.configuration.detail_actions
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_demo_qpane_mask_prefetch_disabled_without_feature(qapp):
    qpane_widget = CuteCanvas(config=Config(), features=())
    try:
        with pytest.raises(FeatureInstallError):
            _ = qpane_widget.settings.mask_prefetch_enabled
    finally:
        qpane_widget.deleteLater()
        qapp.processEvents()


def test_demo_qpane_mask_prefetch_tracks_slice(qapp):
    demo_config = Config()
    demo_config.mask_prefetch_enabled = False
    qpane_widget = CuteCanvas(config=demo_config, features=("mask",))
    try:
        assert qpane_widget.settings.mask_prefetch_enabled is False
        qpane_widget.applySettings(mask_prefetch_enabled=True)
        assert qpane_widget.settings.mask_prefetch_enabled is True
    finally:
        qpane_widget.deleteLater()
        qapp.processEvents()
