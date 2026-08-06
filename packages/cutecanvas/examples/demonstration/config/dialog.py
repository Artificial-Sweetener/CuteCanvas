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

"""Config dialog used by the example to edit CuteCanvas settings."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar

from cutecanvas import Config
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from demonstration.config.spec import (
    _ALL_FIELDS,
    _CONFIG_FIELDS,
    DIAGNOSTIC_DOMAIN_OPTIONS,
    FieldGroupSpec,
    FieldSpec,
    SectionSpec,
    active_namespaces_for_features,
    build_sections_for_features,
    field_sets_for_sections,
)

_SAM_CONFIG_FIELDS: tuple[str, ...] = (
    "sam_download_mode",
    "sam_model_path",
    "sam_model_url",
    "sam_model_hash",
)


class LockedSizeWidget(QWidget):
    """Editor for optional width and height configuration pairs."""

    valueChanged = Signal()

    def __init__(
        self,
        *,
        minimum: int,
        maximum: int,
        step: int,
        initial: tuple[int, int] | None,
        parent: QWidget | None = None,
    ) -> None:
        """Construct paired spin boxes with shared validation."""
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._width = QSpinBox(self)
        self._height = QSpinBox(self)
        for spin in (self._width, self._height):
            spin.setRange(int(minimum), int(maximum))
            spin.setSingleStep(int(step))
            spin.valueChanged.connect(self.valueChanged)
        initial_w, initial_h = self._coerce_size(initial, fallback=int(minimum))
        self._width.setValue(initial_w)
        self._height.setValue(initial_h)
        layout.addWidget(self._width)
        layout.addWidget(QLabel("x", self))
        layout.addWidget(self._height)

    def value(self) -> tuple[int, int]:
        """Return the current size tuple."""
        return (int(self._width.value()), int(self._height.value()))

    @staticmethod
    def _coerce_size(
        value: tuple[int, int] | None, *, fallback: int
    ) -> tuple[int, int]:
        """Sanitize a width/height pair, falling back when invalid."""
        if (
            isinstance(value, tuple)
            and len(value) == 2
            and all(isinstance(v, (int, float)) for v in value)
        ):
            try:
                w = int(value[0])
                h = int(value[1])
            except (IndexError, TypeError, ValueError, OverflowError):
                return fallback, fallback
            if w > 0 and h > 0:
                return w, h
        return fallback, fallback


@dataclass(frozen=True)
class ConfigResult:
    """Diff from the dialog along with context needed for application."""

    values: dict[str, object]
    config_fields: set[str]
    all_fields: set[str]
    restart_fields: set[str]


class DomainCheckboxGroup(QWidget):
    """Grouped checkboxes that expose the selected diagnostics detail domains."""

    def __init__(
        self,
        *,
        domains: Iterable[str],
        selected: Iterable[str] = (),
        labels: Mapping[str, str] | None = None,
        tooltips: Mapping[str, str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the checkbox group with the specified domains and selection."""
        super().__init__(parent)
        self._domains = tuple(domains)
        selected_set = set(selected)
        self._checkboxes: dict[str, QCheckBox] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        for domain in self._domains:
            label = (labels or {}).get(domain, domain.title())
            box = QCheckBox(label, self)
            box.setChecked(domain in selected_set)
            tooltip = (tooltips or {}).get(domain)
            if tooltip:
                box.setToolTip(tooltip)
            layout.addWidget(box)
            self._checkboxes[domain] = box

    def domains(self) -> tuple[str, ...]:
        """Return domains in display order."""
        return self._domains

    def selected_domains(self) -> tuple[str, ...]:
        """Return enabled domains in display order."""
        return tuple(
            domain for domain in self._domains if self._checkboxes[domain].isChecked()
        )

    def checkboxes(self) -> tuple[QCheckBox, ...]:
        """Expose the underlying checkboxes for signal wiring."""
        return tuple(self._checkboxes.values())


class FilterStatusLabel(QLabel):
    """QLabel that reports the requested visibility state for tests."""

    def __init__(self, *args, **kwargs) -> None:
        """Track the last requested visibility for diagnostics/tests."""
        super().__init__(*args, **kwargs)
        self._explicit_visible = False

    def setVisible(self, visible: bool) -> None:  # type: ignore[override]
        """Record visibility requests before forwarding to QLabel."""
        self._explicit_visible = visible
        super().setVisible(visible)

    def isVisible(self) -> bool:  # type: ignore[override]
        """Expose the last requested visibility instead of QWidget state."""
        return self._explicit_visible


class ConfigDialog(QDialog):
    """Dialog that edits CuteCanvas configuration settings for the demo.

    Args:
        config: Starting Config snapshot to edit.
        parent: Optional parent widget.
        active_features: Installed feature names used to hide gated controls.
    """

    ALL_FIELDS: ClassVar[set[str]] = _ALL_FIELDS
    CONFIG_FIELDS: ClassVar[set[str]] = _CONFIG_FIELDS
    SAM_FIELDS: ClassVar[set[str]] = set(_SAM_CONFIG_FIELDS)

    def __init__(
        self,
        config: Config,
        parent: QWidget | None = None,
        *,
        baseline: Config | None = None,
        active_features: Sequence[str] | None = None,
    ) -> None:
        """Initialize the configuration dialog with a snapshot of the current settings."""
        super().__init__(parent)
        self.setWindowTitle("CuteCanvas Configuration")
        self.setModal(True)
        self.setMinimumWidth(420)
        self._original = config.copy()
        self._baseline = baseline.copy() if baseline is not None else Config()
        self._original_snapshot = self._original.as_dict()
        self._baseline_snapshot = self._baseline.as_dict()
        self._active_features = (
            tuple(active_features) if active_features is not None else None
        )
        self._active_namespaces = active_namespaces_for_features(self._active_features)
        self._diagnostic_domain_labels = {
            domain: label for domain, label, _tooltip, _ns in DIAGNOSTIC_DOMAIN_OPTIONS
        }
        self._diagnostic_domain_tooltips = {
            domain: tooltip
            for domain, _label, tooltip, _ns in DIAGNOSTIC_DOMAIN_OPTIONS
        }
        self._sections: tuple[SectionSpec, ...] = build_sections_for_features(
            self._active_features
        )
        (
            self._all_fields,
            self._config_fields,
            self._field_specs,
        ) = field_sets_for_sections(self._sections)
        self._widgets: dict[str, QWidget] = {}
        self._field_containers: dict[str, QWidget] = {}
        self._field_labels: dict[str, QWidget] = {}
        self._section_items: dict[str, QWidget] = {}
        self._section_terms: dict[str, set[str]] = {}
        self._tab_indices: dict[str, int] = {}
        self._cache_mode: QComboBox | None = None
        self._cache_headroom_percent: QWidget | None = None
        self._cache_headroom_cap: QWidget | None = None
        self._cache_budget: QWidget | None = None
        self._sam_download_mode: QComboBox | None = None
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(16)
        filter_row = QHBoxLayout()
        filter_label = QLabel("Filter", self)
        self._filter_input = QLineEdit(self)
        self._filter_input.setPlaceholderText("Search settings")
        self._filter_input.textChanged.connect(self._apply_filter)
        self._no_matches_label = FilterStatusLabel("No matching sections", self)
        self._no_matches_label.setVisible(False)
        filter_row.addWidget(filter_label)
        filter_row.addWidget(self._filter_input, 1)
        filter_row.addWidget(self._no_matches_label)
        root_layout.addLayout(filter_row)
        tabs = QTabWidget(self)
        self._tabs = tabs
        self._tab_layouts: dict[str, QVBoxLayout] = {}
        self._build_sections(tabs)
        root_layout.addWidget(tabs)
        preview_box = QGroupBox("Config Preview", self)
        preview_layout = QVBoxLayout(preview_box)
        preview_layout.setContentsMargins(12, 8, 12, 12)
        preview_layout.setSpacing(8)
        self._preview_status_label = QLabel("No changes yet", preview_box)
        self._preview_text = QPlainTextEdit(preview_box)
        self._preview_text.setReadOnly(True)
        preview_layout.addWidget(self._preview_status_label)
        preview_layout.addWidget(self._preview_text)
        root_layout.addWidget(preview_box)
        ok_button = QDialogButtonBox.StandardButton.Ok
        cancel_button = QDialogButtonBox.StandardButton.Cancel
        button_box = QDialogButtonBox(ok_button | cancel_button, parent=self)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        root_layout.addWidget(
            button_box,
            alignment=Qt.AlignmentFlag.AlignRight,
        )
        self._apply_filter(self._filter_input.text())
        self._update_preview()

    def _build_sections(self, tabs: QTabWidget) -> None:
        """Create tabbed form controls for each configurable setting."""
        for section in self._sections:
            tab_title = section.title
            scroll = QScrollArea(self)
            scroll.setWidgetResizable(True)
            page = QWidget(scroll)
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(12, 12, 12, 12)
            page_layout.setSpacing(12)
            for group in section.groups:
                group_box = QGroupBox(group.title, page)
                group_layout = QFormLayout(group_box)
                group_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
                group_layout.setLabelAlignment(
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                )
                group_layout.setHorizontalSpacing(12)
                group_layout.setVerticalSpacing(6)
                for spec in group.fields:
                    widget = self._create_widget(spec)
                    value_widget = getattr(widget, "_value_widget", widget)
                    self._widgets[spec.path] = value_widget
                    self._field_containers[spec.path] = widget
                    label_text = self._label_for(spec.path, spec.label)
                    group_layout.addRow(label_text, widget)
                    label_widget = group_layout.labelForField(widget)
                    if label_widget is not None:
                        self._field_labels[spec.path] = label_widget
                page_layout.addWidget(group_box)
            page_layout.addStretch()
            scroll.setWidget(page)
            index = tabs.addTab(scroll, tab_title)
            self._tab_layouts[tab_title] = page_layout
            self._section_items[tab_title] = scroll
            self._section_terms[tab_title] = self._collect_section_terms(
                tab_title, section.groups
            )
            self._tab_indices[tab_title] = index
        self._sync_cache_mode_fields()

    def _allowed_diagnostic_domains(self, requested: Sequence[str]) -> tuple[str, ...]:
        """Filter diagnostic domains based on active feature namespaces."""
        namespace_lookup = {
            domain: namespace for domain, _, _, namespace in DIAGNOSTIC_DOMAIN_OPTIONS
        }
        return tuple(
            domain
            for domain in requested
            if namespace_lookup.get(domain) is None
            or namespace_lookup.get(domain) in self._active_namespaces
        )

    def _config_value(
        self, name: str, *, source: Mapping[str, object] | None = None
    ) -> object:
        """Return the current value for a dotted config path."""
        config_source = source if source is not None else self._original_snapshot
        parts = name.split(".")
        if parts and parts[0] == "cache":
            cache_settings = (
                config_source.get("cache") if isinstance(config_source, Mapping) else {}
            )
            if not isinstance(cache_settings, Mapping):
                return None
            _, *tail = parts
            if not tail:
                return cache_settings
            head = tail[0]
            if head in {"mode", "headroom_percent", "headroom_cap_mb", "budget_mb"}:
                return cache_settings.get(head)
            if head == "weights" and len(tail) == 2:
                ratios = cache_settings.get("weights", {})
                if isinstance(ratios, Mapping):
                    return ratios.get(tail[1])
                return None
            if head == "weights" and len(tail) == 3 and tail[1] == "extensions":
                ratios = cache_settings.get("weights", {})
                extensions = (
                    ratios.get("extensions", {}) if isinstance(ratios, Mapping) else {}
                )
                return (
                    extensions.get(tail[2]) if isinstance(extensions, Mapping) else None
                )
            if head in {"tiles", "pyramids"}:
                bucket = cache_settings.get(head)
                if len(tail) == 2 and tail[1] == "mb" and isinstance(bucket, Mapping):
                    override = bucket.get("mb")
                    return -1 if override is None else override
            if head == "extensions" and len(tail) == 3 and tail[2] == "mb":
                extensions = cache_settings.get("extensions", {})
                bucket = (
                    extensions.get(tail[1]) if isinstance(extensions, Mapping) else None
                )
                if isinstance(bucket, Mapping):
                    override = bucket.get("mb")
                    return -1 if override is None else override
            if head == "prefetch" and len(tail) == 2:
                prefetch = cache_settings.get("prefetch")
                if isinstance(prefetch, Mapping):
                    return prefetch.get(tail[1])
            if head == "prefetch" and len(tail) == 3 and tail[1] == "extensions":
                prefetch = cache_settings.get("prefetch", {})
                extensions = (
                    prefetch.get("extensions", {})
                    if isinstance(prefetch, Mapping)
                    else {}
                )
                return (
                    extensions.get(tail[2]) if isinstance(extensions, Mapping) else None
                )
            return None
        value: object = config_source
        for part in parts:
            if value is None:
                return None
            if isinstance(value, Mapping):
                value = value.get(part)
                continue
            try:
                value = getattr(value, part)
            except AttributeError:
                return None
        return value

    def _initial_value(self, spec: FieldSpec) -> object:
        """Return a safe initial value for the provided field spec."""
        value = self._config_value(spec.path, source=self._original_snapshot)
        if value is not None:
            return value
        if spec.kind == "spin":
            if spec.minimum is not None:
                return int(spec.minimum)
            return 0
        if spec.kind == "double":
            if spec.minimum is not None:
                return float(spec.minimum)
            return 0.0
        if spec.kind == "checkbox":
            return False
        if spec.kind in ("line", "path"):
            return ""
        if spec.kind == "combo":
            return spec.options[0] if spec.options else ""
        if spec.kind == "size":
            minimum = int(spec.minimum) if spec.minimum is not None else 1
            return (minimum, minimum)
        if spec.kind == "multicheck":
            if isinstance(value, (list, tuple, set)):
                return tuple(value)
            return ()
        return None

    def _create_widget(self, spec: FieldSpec) -> QWidget:
        """Instantiate a control for the provided field specification."""
        current_value = self._initial_value(spec)
        if spec.kind == "combo":
            widget = QComboBox(self)
            for option in spec.options or ():
                widget.addItem(option)
            if isinstance(current_value, str):
                index = widget.findText(current_value)
                if index >= 0:
                    widget.setCurrentIndex(index)
            if spec.path == "cache.mode":
                widget.currentTextChanged.connect(self._handle_cache_mode_changed)
                self._cache_mode = widget
            if spec.path == "sam_download_mode":
                self._sam_download_mode = widget
            self._wire_widget_signals(widget)
            return widget
        if spec.kind == "spin":
            if spec.minimum is None or spec.maximum is None:
                raise ValueError(f"Spin fields require bounds: {spec.path}")
            widget = QSpinBox(self)
            widget.setRange(int(spec.minimum), int(spec.maximum))
            widget.setSingleStep(int(spec.step or 1))
            widget.setValue(int(current_value))
            if spec.special_value_text:
                widget.setSpecialValueText(spec.special_value_text)
            if spec.path == "cache.headroom_cap_mb":
                self._cache_headroom_cap = widget
            if spec.path == "cache.budget_mb":
                self._cache_budget = widget
        elif spec.kind == "double":
            if spec.minimum is None or spec.maximum is None:
                raise ValueError(f"Double fields require bounds: {spec.path}")
            widget = QDoubleSpinBox(self)
            widget.setDecimals(spec.decimals or 2)
            widget.setRange(float(spec.minimum), float(spec.maximum))
            widget.setSingleStep(float(spec.step or 0.1))
            widget.setValue(float(current_value))
            if spec.special_value_text:
                widget.setSpecialValueText(spec.special_value_text)
            if spec.path == "cache.headroom_percent":
                self._cache_headroom_percent = widget
        elif spec.kind == "size":
            if spec.minimum is None or spec.maximum is None:
                raise ValueError(f"Size fields require bounds: {spec.path}")
            initial_size = self._normalize_size_value(current_value)
            widget = LockedSizeWidget(
                minimum=int(spec.minimum),
                maximum=int(spec.maximum),
                step=int(spec.step or 1),
                initial=initial_size,
                parent=self,
            )
        elif spec.kind == "checkbox":
            widget = QCheckBox(self)
            widget.setChecked(bool(current_value))
        elif spec.kind == "line":
            widget = QLineEdit(self)
            widget.setText(str(current_value))
            widget.setClearButtonEnabled(True)
            if spec.placeholder:
                widget.setPlaceholderText(spec.placeholder)
        elif spec.kind == "path":
            line_edit = QLineEdit(self)
            line_edit.setText(str(current_value))
            line_edit.setClearButtonEnabled(True)
            if spec.placeholder:
                line_edit.setPlaceholderText(spec.placeholder)
            browse = QPushButton("Browse", self)
            browse.clicked.connect(
                lambda *_, current=spec, target=line_edit: self._browse_for_path(
                    current,
                    target,
                )
            )
            container = QWidget(self)
            layout = QHBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(6)
            layout.addWidget(line_edit, 1)
            layout.addWidget(browse, 0)
            self._wire_widget_signals(line_edit)
            container._value_widget = line_edit  # type: ignore[attr-defined]
            layout.setStretch(0, 1)
            return container
        elif spec.kind == "multicheck":
            available_domains = self._allowed_diagnostic_domains(spec.options or ())
            selected = (
                tuple(current_value)
                if isinstance(current_value, (list, tuple, set))
                else ()
            )
            widget = DomainCheckboxGroup(
                domains=available_domains,
                selected=selected,
                labels=self._diagnostic_domain_labels,
                tooltips=self._diagnostic_domain_tooltips,
                parent=self,
            )
        else:
            raise ValueError(f"Unsupported field kind: {spec.kind}")
        if spec.suffix and isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            widget.setSuffix(spec.suffix)
        if spec.tooltip:
            widget.setToolTip(spec.tooltip)
        self._wire_widget_signals(widget)
        return widget

    def _browse_for_path(self, spec: FieldSpec, line_edit: QLineEdit) -> None:
        """Choose one file suitable for a path-valued setting."""
        title = (
            "Select Model Checkpoint"
            if spec.path == "sam_model_path"
            else "Select File"
        )
        file_filter = (
            "Model checkpoints (*.pt *.pth);;All files (*)"
            if spec.path == "sam_model_path"
            else "All files (*)"
        )
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            title,
            "",
            file_filter,
        )
        if file_path:
            line_edit.setText(file_path)

    def _label_for(self, name: str, override: str | None = None) -> str:
        """Render a human-friendly label for a config path."""
        return override or name.replace("_", " ").title()

    @staticmethod
    def _normalize_size_value(value: object) -> tuple[int, int] | None:
        """Return a sanitized width/height pair when valid."""
        if isinstance(value, (tuple, list)) and len(value) == 2:
            try:
                width = int(value[0])
                height = int(value[1])
            except (TypeError, ValueError):
                return None
            if width > 0 and height > 0:
                return (width, height)
        return None

    def result(self) -> ConfigResult:
        """Return the dialog results plus config metadata for application."""
        values = self._diff_against(self._original_snapshot)
        restart_fields = self._sam_restart_fields(values)
        return ConfigResult(
            values=values,
            config_fields=set(self._config_fields),
            all_fields=set(self._all_fields),
            restart_fields=restart_fields,
        )

    @staticmethod
    def collapse_values(values: Mapping[str, object]) -> dict[str, object]:
        """Convert dotted keys into nested dictionaries for downstream consumers."""
        collapsed: dict[str, object] = {}
        for key, value in values.items():
            if "." not in key:
                collapsed[key] = value
                continue
            parts = key.split(".")
            head = parts[0]
            cursor = collapsed.get(head)
            if not isinstance(cursor, dict):
                cursor = {}
                collapsed[head] = cursor
            for part in parts[1:-1]:
                next_node = cursor.get(part)
                if not isinstance(next_node, dict):
                    next_node = {}
                    cursor[part] = next_node
                cursor = next_node
            cursor[parts[-1]] = value
        return collapsed

    def _collect_section_terms(
        self,
        tab_title: str,
        groups: tuple[FieldGroupSpec, ...],
    ) -> set[str]:
        """Assemble lowercase tokens for matching filter queries."""
        terms: set[str] = {tab_title.lower()}
        for group in groups:
            terms.add(group.title.lower())
        return terms

    def _apply_filter(self, text: str | None = None) -> None:
        """Toggle tab visibility so only matching sections remain."""
        query = (
            (text if text is not None else self._filter_input.text()).strip().lower()
        )
        any_visible = False
        for title, widget in self._section_items.items():
            tokens = self._section_terms.get(title, set())
            matches = not query or any(query in token for token in tokens)
            widget.setVisible(matches)
            index = self._tab_indices.get(title)
            if index is not None:
                self._tabs.setTabVisible(index, matches)
            if matches:
                any_visible = True
        self._no_matches_label.setVisible(bool(query) and not any_visible)

    def _wire_widget_signals(self, widget: QWidget) -> None:
        """Attach change listeners so the preview stays in sync."""
        if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            widget.valueChanged.connect(self._trigger_preview_update)
        elif isinstance(widget, QCheckBox):
            widget.toggled.connect(self._trigger_preview_update)
        elif isinstance(widget, QLineEdit):
            widget.textChanged.connect(self._trigger_preview_update)
        elif isinstance(widget, QComboBox):
            widget.currentTextChanged.connect(self._trigger_preview_update)
        elif isinstance(widget, DomainCheckboxGroup):
            for box in widget.checkboxes():
                box.toggled.connect(self._trigger_preview_update)

    def _handle_cache_mode_changed(self, *_args) -> None:
        """Toggle cache budget controls when the mode changes."""
        self._sync_cache_mode_fields()
        self._trigger_preview_update()

    def _sync_cache_mode_fields(self) -> None:
        """Show Auto headroom controls or Hard budget based on the selected mode."""
        mode_widget = self._cache_mode
        mode_source = (
            mode_widget.currentText()
            if mode_widget is not None
            else str(self._config_value("cache.mode") or "")
        )
        mode = mode_source.lower()
        auto_mode = mode == "auto"
        self._set_field_visible("cache.headroom_percent", auto_mode)
        self._set_field_visible("cache.headroom_cap_mb", auto_mode)
        self._set_field_visible("cache.budget_mb", not auto_mode)
        for path, enabled in (
            ("cache.headroom_percent", auto_mode),
            ("cache.headroom_cap_mb", auto_mode),
            ("cache.budget_mb", not auto_mode),
        ):
            widget = self._widgets.get(path)
            if widget is not None:
                widget.setEnabled(enabled)

    def _set_field_visible(self, path: str, visible: bool) -> None:
        """Toggle both the input widget and its label visibility."""
        container = self._field_containers.get(path)
        if container is not None:
            container.setVisible(visible)
        label = self._field_labels.get(path)
        if label is not None:
            label.setVisible(visible)

    def _sam_download_mode_value(self) -> str:
        """Return the selected SAM download mode for restart guidance."""
        widget = self._sam_download_mode
        if widget is not None:
            return widget.currentText().strip().lower()
        value = self._config_value("sam_download_mode")
        return "" if value is None else str(value).strip().lower()

    def _sam_restart_fields(self, values: Mapping[str, object]) -> set[str]:
        """Return SAM fields that require restart based on the current mode."""
        changed = {name for name in values if name in self.SAM_FIELDS}
        if not changed:
            return set()
        mode = self._sam_download_mode_value()
        if mode == "background":
            return set()
        return changed

    def _trigger_preview_update(self, *_args) -> None:
        """Recompute the preview when any field value changes."""
        self._update_preview()

    def _update_preview(self) -> None:
        """Render the collapsed config diff in the preview qpane."""
        preview_values = self._diff_against(self._baseline_snapshot)
        if not preview_values:
            self._preview_status_label.setText("No changes yet")
            self._preview_text.clear()
            return
        restart_fields = self._sam_restart_fields(preview_values)
        if restart_fields:
            self._preview_status_label.setText(
                "Restart required for SAM changes (blocking/disabled)."
            )
        else:
            self._preview_status_label.setText("Applies live")
        collapsed = self.collapse_values(preview_values)
        self._preview_text.setPlainText(json.dumps(collapsed, indent=2, sort_keys=True))

    def _diff_against(
        self,
        reference_snapshot: Mapping[str, object],
    ) -> dict[str, object]:
        """Return the flattened config diff relative to the provided baselines."""
        values: dict[str, object] = {}
        for name, widget in self._widgets.items():
            spec = self._field_specs.get(name)
            reference_value = (
                self._config_value(name, source=reference_snapshot) if spec else None
            )
            current, normalized_reference = self._widget_state(
                widget, spec, reference_value
            )
            if current != normalized_reference:
                values[name] = current
        return values

    def _widget_state(
        self,
        widget: QWidget,
        spec: FieldSpec | None,
        reference_value: object,
    ) -> tuple[object, object]:
        """Return the current widget value and normalized reference."""
        if isinstance(widget, QSpinBox):
            raw_value = widget.value()
            current: object = int(raw_value)
            normalized_reference = (
                int(reference_value) if reference_value is not None else None
            )
            if spec and spec.special_value_text and spec.minimum is not None:
                threshold = int(spec.minimum)
                current = None if raw_value <= threshold else current
                if normalized_reference is not None:
                    normalized_reference = (
                        None
                        if int(normalized_reference) <= threshold
                        else int(normalized_reference)
                    )
            if (
                normalized_reference is None
                and spec is not None
                and spec.minimum is not None
                and current == int(spec.minimum)
            ):
                normalized_reference = current
            return current, normalized_reference
        if isinstance(widget, QDoubleSpinBox):
            raw_value = widget.value()
            current = float(raw_value)
            normalized_reference = (
                float(reference_value) if reference_value is not None else None
            )
            if spec and spec.special_value_text and spec.minimum is not None:
                threshold = float(spec.minimum)
                current = None if raw_value <= threshold else current
                if normalized_reference is not None:
                    normalized_reference = (
                        None
                        if float(normalized_reference) <= threshold
                        else float(normalized_reference)
                    )
            return current, normalized_reference
        if isinstance(widget, QCheckBox):
            current = widget.isChecked()
            normalized_reference = bool(reference_value)
            return current, normalized_reference
        if isinstance(widget, QLineEdit):
            current = widget.text()
            normalized_reference = (
                "" if reference_value is None else str(reference_value)
            )
            return current, normalized_reference
        if isinstance(widget, QComboBox):
            current = widget.currentText()
            normalized_reference = (
                "" if reference_value is None else str(reference_value)
            )
            return current, normalized_reference
        if isinstance(widget, DomainCheckboxGroup):
            current = widget.selected_domains()
            reference_set = set(reference_value or ())
            normalized_reference = tuple(
                domain for domain in widget.domains() if domain in reference_set
            )
            return current, normalized_reference
        if isinstance(widget, LockedSizeWidget):
            current_tuple = widget.value()
            current = (
                (int(current_tuple[0]), int(current_tuple[1]))
                if current_tuple and all(v > 0 for v in current_tuple)
                else None
            )
            normalized_reference = self._normalize_size_value(reference_value)
            return current, normalized_reference
        return reference_value, reference_value
