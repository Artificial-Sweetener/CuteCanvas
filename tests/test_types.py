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

"""Tests for the public types and enums exposed by the qpane facade."""

import uuid
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from cutecanvas import (
    CacheMode,
    CatalogEntry,
    CatalogLayerRequest,
    CompositionRequest,
    CompositionTemplate,
    ControlMode,
    DiagnosticsDomain,
    LayerSnapshot,
    LinkedGroup,
    PlaceholderScaleMode,
    SceneSnapshot,
    TemplateBindings,
    TemplateLayer,
    ZoomMode,
)
from cutecanvas.types import __all__ as exported_editor_types
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage
from qpane.types import DiagnosticRecord
from qpane.types import __all__ as exported_viewer_types


def test_viewer_type_exports_are_listed() -> None:
    expected = {
        "CacheMode",
        "PlaceholderScaleMode",
        "ZoomMode",
        "DiagnosticsDomain",
        "CatalogEntry",
        "LinkedGroup",
        "DiagnosticRecord",
        "ComparisonOrientation",
        "ComparisonState",
        "ComparisonDividerState",
        "OverlayState",
        "SceneSnapshotOverlayState",
        "SceneSnapshotOverlayLayer",
    }
    assert expected == set(exported_viewer_types)


def test_editor_type_exports_are_listed() -> None:
    expected = {
        "ControlMode",
        "SceneSnapshot",
        "LayerSnapshot",
        "CompositionRequest",
        "CatalogLayerRequest",
        "CompositionTemplate",
        "TemplateLayer",
        "TemplateBindings",
        "CompositionLayerClip",
        "LayerHit",
    }
    assert expected.issubset(set(exported_editor_types))


def test_enum_values_match_facade_contract() -> None:
    assert {mode.value for mode in CacheMode} == {"auto", "hard"}
    assert {mode.value for mode in PlaceholderScaleMode} == {
        "auto",
        "logical_fit",
        "physical_fit",
        "relative_fit",
    }
    assert {mode.value for mode in ZoomMode} == {"fit", "locked_zoom", "locked_size"}
    assert {mode.value for mode in DiagnosticsDomain} == {
        "cache",
        "swap",
        "render",
        "mask",
        "executor",
        "retry",
        "sam",
    }
    assert {mode.value for mode in ControlMode} == {
        "cursor",
        "panzoom",
        "move",
        "transform",
        "draw-brush",
        "smart-select",
        "select-rectangle",
        "select-ellipse",
        "select-lasso",
        "vector-shape",
        "vector-path",
        "vector-node",
        "vector-text",
    }


def test_catalog_entry_is_frozen_and_slotted() -> None:
    image = QImage(1, 1, QImage.Format_ARGB32)
    entry = CatalogEntry(image=image, path=None)
    assert entry.image is image
    assert entry.path is None
    with pytest.raises(FrozenInstanceError):
        entry.path = Path("other.png")  # type: ignore[misc]
    with pytest.raises((AttributeError, TypeError)):
        entry.extra = "forbidden"  # type: ignore[attr-defined]


def test_linked_group_is_frozen_and_preserves_members() -> None:
    group_id = uuid.uuid4()
    members = (uuid.uuid4(), uuid.uuid4())
    group = LinkedGroup(group_id=group_id, members=members)
    assert group.group_id == group_id
    assert group.members == members
    with pytest.raises(FrozenInstanceError):
        group.members = ()  # type: ignore[misc]


def test_diagnostic_record_formatting() -> None:
    record = DiagnosticRecord("Label", "Value")
    assert record.formatted() == "Label: Value"
    assert str(record) == "Label: Value"
    standalone = DiagnosticRecord("", "Solo")
    assert standalone.formatted() == "Solo"


def test_scene_layer_copies_metadata_and_geometry() -> None:
    """Public scene types should preserve snapshots instead of caller-owned objects."""
    image_id = uuid.uuid4()
    layer_id = uuid.uuid4()
    placement = QRectF(0, 0, 10, 10)
    metadata = {"record": {"id": 1}}
    tint = QColor(20, 140, 220, 180)

    layer = LayerSnapshot(
        layer_id=layer_id,
        image_id=image_id,
        placement=placement,
        metadata=metadata,
        tint=tint,
    )
    scene = SceneSnapshot(
        composition_id=uuid.uuid4(),
        scene_id=uuid.uuid4(),
        title="Scene",
        bounds=QRectF(0, 0, 10, 10),
        layers=(layer,),
    )
    request = CompositionRequest(
        composition_id=None,
        title=None,
        bounds=QRectF(0, 0, 10, 10),
        layers=(
            CatalogLayerRequest(
                layer_id=layer_id,
                image_id=image_id,
                placement=placement,
                metadata=metadata,
            ),
        ),
    )
    template = CompositionTemplate(
        template_id=uuid.uuid4(),
        bounds=QRectF(0, 0, 10, 10),
        layers=(
            TemplateLayer(
                layer_id=uuid.uuid4(),
                source_slot="image",
                placement=placement,
                metadata=metadata,
            ),
        ),
    )
    bindings = TemplateBindings(
        composition_id=None,
        catalog_images={"image": image_id},
        metadata={"image": metadata},
    )
    placement.setWidth(50)
    tint.setRed(255)
    metadata["other"] = True

    assert layer.placement.width() == 10
    assert layer.tint == QColor(20, 140, 220, 180)
    assert "other" not in layer.metadata
    assert scene.layers == (layer,)
    assert request.layers[0].placement.width() == 10
    assert "other" not in request.layers[0].metadata
    assert template.layers[0].placement.width() == 10
    assert "other" not in template.layers[0].metadata
    assert "other" not in bindings.metadata["image"]
    with pytest.raises(TypeError):
        layer.metadata["other"] = False  # type: ignore[index]
