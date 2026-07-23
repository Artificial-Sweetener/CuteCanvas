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

"""Builders that translate CuteCanvas catalog snapshots into demo presentation models."""

from __future__ import annotations

import uuid
from pathlib import Path

from cutecanvas import CatalogSnapshot, CuteCanvas, LinkedGroup

from examples.demonstration.catalog.models import (
    CatalogGroup,
    CatalogImage,
    CatalogMask,
)
from examples.demonstration.catalog.models import (
    CatalogSnapshot as CatalogTreeSnapshot,
)


def build_catalog_snapshot(qpane: CuteCanvas) -> CatalogTreeSnapshot:
    """Assemble grouped catalog data from the CuteCanvas facade snapshot helper."""
    snapshot: CatalogSnapshot = qpane.getCatalogSnapshot()
    if not snapshot.order:
        return CatalogTreeSnapshot(
            groups=[],
            current_image_id=snapshot.current_image_id,
            active_mask_id=snapshot.active_mask_id,
            image_count=0,
            mask_capable=snapshot.mask_capable,
        )
    ordering = {image_id: idx for idx, image_id in enumerate(snapshot.order)}
    sorted_records: list[LinkedGroup] = []
    for group in snapshot.linked_groups:
        valid_members = [mid for mid in group.members if mid in ordering]
        if len(valid_members) < 2:
            continue
        valid_members.sort(key=ordering.get)
        sorted_records.append(
            LinkedGroup(group_id=group.group_id, members=tuple(valid_members))
        )
    sorted_records.sort(key=lambda item: ordering[item.members[0]])
    assigned: set[uuid.UUID] = set()
    groups: list[CatalogGroup] = []
    for group in sorted_records:
        assigned.update(group.members)
        images = [
            _build_catalog_image(
                qpane=qpane,
                image_id=image_id,
                index=ordering[image_id],
                active_mask_id=snapshot.active_mask_id,
                link_id=group.group_id,
                path=snapshot.catalog[image_id].path,
            )
            for image_id in group.members
        ]
        groups.append(
            CatalogGroup(
                group_id=group.group_id,
                title=_format_link_title(group.group_id),
                images=images,
                is_link_group=True,
            )
        )
    unlinked_ids = [image_id for image_id in snapshot.order if image_id not in assigned]
    if unlinked_ids:
        unlinked_images = [
            _build_catalog_image(
                qpane=qpane,
                image_id=image_id,
                index=ordering[image_id],
                active_mask_id=snapshot.active_mask_id,
                link_id=None,
                path=snapshot.catalog[image_id].path,
            )
            for image_id in unlinked_ids
        ]
        groups.append(
            CatalogGroup(
                group_id=None,
                title="Unlinked",
                images=unlinked_images,
                is_link_group=False,
            )
        )
    return CatalogTreeSnapshot(
        groups=groups,
        current_image_id=snapshot.current_image_id,
        active_mask_id=snapshot.active_mask_id,
        image_count=len(snapshot.order),
        mask_capable=snapshot.mask_capable,
    )


def _build_catalog_image(
    *,
    qpane: CuteCanvas,
    image_id: uuid.UUID,
    index: int,
    active_mask_id: uuid.UUID | None,
    link_id: uuid.UUID | None,
    path: Path | None,
) -> CatalogImage:
    """Create a display record for ``image_id`` including mask entries."""
    label = _format_image_label(path, index)
    masks = _collect_mask_entries(qpane, image_id, active_mask_id)
    return CatalogImage(
        image_id=image_id,
        label=label,
        index=index,
        path=path,
        is_current=qpane.currentImageID() == image_id,
        link_id=link_id,
        masks=masks,
    )


def _collect_mask_entries(
    qpane: CuteCanvas, image_id: uuid.UUID, active_mask_id: uuid.UUID | None
) -> list[CatalogMask]:
    """Return mask presentation data for ``image_id``."""
    if not qpane.maskFeatureAvailable():
        return []
    mask_info = qpane.listMasksForImage(image_id)
    entries: list[CatalogMask] = []
    # Render top-most mask first so ordering matches the active stack.
    for summary in reversed(mask_info):
        label = _format_mask_label(summary.label, summary.mask_id)
        entries.append(
            CatalogMask(
                mask_id=summary.mask_id,
                label=label,
                color=summary.color,
                is_active=summary.mask_id == active_mask_id,
            )
        )
    return entries


def _format_image_label(path: Path | None, index: int) -> str:
    """Return a descriptive label for an image based on its source path."""
    if path is None:
        return f"Image {index + 1}"
    return path.name


def _format_mask_label(label_source, mask_id: uuid.UUID) -> str:
    """Return the preferred label for a mask layer."""
    label = label_source
    if not isinstance(label, str):
        label = getattr(label_source, "label", None)
    if isinstance(label, str):
        label = label.strip()
    if label:
        return label
    short_id = mask_id.hex[:8].upper()
    return f"Mask {short_id}"


def _format_link_title(group_id: uuid.UUID) -> str:
    """Return a user-facing label for a link group identifier."""
    return f"Link {group_id.hex[:8].upper()}"
