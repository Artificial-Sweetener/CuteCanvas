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
"""Bounded retention and complete-coverage lookup for sampled render tiles."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Hashable

from PySide6.QtCore import QRectF

from .render_tile_geometry import RenderTileKey, RenderTileRequest
from .render_tile_types import RenderTileProduct


class RenderTileCache:
    """Own shared least-recently-used sampled tiles under a byte ceiling."""

    def __init__(self, budget_bytes: int = 32 * 1024 * 1024) -> None:
        """Initialize an empty coordinated cache."""
        self._budget_bytes = max(0, int(budget_bytes))
        self._usage_bytes = 0
        self._entries: OrderedDict[RenderTileKey, RenderTileProduct] = OrderedDict()
        self._usage_changed: Callable[[int], None] | None = None

    @property
    def usage_bytes(self) -> int:
        """Return retained image bytes."""
        return self._usage_bytes

    @property
    def entry_count(self) -> int:
        """Return the number of retained tiles."""
        return len(self._entries)

    @property
    def budget_bytes(self) -> int:
        """Return the active strict retention ceiling."""
        return self._budget_bytes

    def set_usage_changed(self, callback: Callable[[int], None] | None) -> None:
        """Install shared-cache usage publication."""
        self._usage_changed = callback

    def set_budget(self, budget_bytes: int) -> None:
        """Apply a strict cache budget and trim immediately."""
        self._budget_bytes = max(0, int(budget_bytes))
        self.trim_to(self._budget_bytes)

    def trim_to(self, target_bytes: int) -> None:
        """Evict oldest tiles until usage meets ``target_bytes``."""
        self._trim_to(max(0, int(target_bytes)), frozenset())

    def products(
        self,
        keys: tuple[RenderTileKey, ...],
    ) -> tuple[RenderTileProduct, ...] | None:
        """Return an atomic complete tile set, or ``None`` when any tile is cold."""
        if any(key not in self._entries for key in keys):
            return None
        products: list[RenderTileProduct] = []
        for key in keys:
            product = self._entries.pop(key)
            self._entries[key] = product
            products.append(product)
        return tuple(products)

    def contains(self, key: RenderTileKey) -> bool:
        """Return whether one exact sampled tile is retained."""
        return key in self._entries

    def covering_products(
        self,
        requests: tuple[RenderTileRequest, ...],
    ) -> tuple[RenderTileProduct, ...] | None:
        """Return one compatible revision covering every requested core."""
        if not requests:
            return ()
        first = requests[0].key
        candidates = tuple(
            product
            for product in self._entries.values()
            if product.key.source_kind == first.source_kind
            and product.key.source_id == first.source_id
            and product.key.fallback_key == first.fallback_key
        )
        revisions: list[Hashable] = [first.revision_key]
        for candidate in reversed(candidates):
            revision = candidate.key.revision_key
            if revision not in revisions:
                revisions.append(revision)
        for revision in revisions:
            selected: dict[RenderTileKey, RenderTileProduct] = {}
            for request in requests:
                covering = tuple(
                    product
                    for product in candidates
                    if product.key.revision_key == revision
                    and _contains_rect(product.source_rect, request.source_rect)
                )
                if not covering:
                    break
                product = max(covering, key=lambda candidate: candidate.key.scale)
                selected[product.key] = product
            else:
                keys = tuple(
                    product.key
                    for product in sorted(
                        selected.values(),
                        key=lambda candidate: candidate.key.scale,
                    )
                )
                return self.products(keys)
        return None

    def presentation_products(
        self,
        requests: tuple[RenderTileRequest, ...],
    ) -> tuple[RenderTileProduct, ...] | None:
        """Layer exact tiles over fallback products covering only cold cores."""
        exact_requests = tuple(
            request for request in requests if request.key in self._entries
        )
        missing_requests = tuple(
            request for request in requests if request.key not in self._entries
        )
        exact = self.products(tuple(request.key for request in exact_requests)) or ()
        if not missing_requests:
            return exact
        fallback = self.covering_products(missing_requests)
        if fallback is None:
            return None
        fallback_slices = tuple(
            _clip_product_to_request(
                max(
                    (
                        product
                        for product in fallback
                        if _contains_rect(product.source_rect, request.source_rect)
                    ),
                    key=lambda product: product.key.scale,
                ),
                request,
            )
            for request in missing_requests
        )
        return (*fallback_slices, *exact)

    def admit(
        self,
        products: tuple[RenderTileProduct, ...],
        *,
        retain_keys: tuple[RenderTileKey, ...] = (),
    ) -> None:
        """Admit one complete worker batch without exceeding the byte ceiling."""
        if not products:
            return
        for product in products:
            previous = self._entries.pop(product.key, None)
            if previous is not None:
                self._usage_bytes -= previous.retained_bytes
            if product.retained_bytes <= self._budget_bytes:
                self._entries[product.key] = product
                self._usage_bytes += product.retained_bytes
        self._trim_to(self._budget_bytes, frozenset(retain_keys))

    def _trim_to(
        self,
        target_bytes: int,
        retained_keys: frozenset[RenderTileKey],
    ) -> None:
        """Meet one byte target while preserving the active guarded batch."""
        target = max(0, int(target_bytes))
        while self._entries and self._usage_bytes > target:
            eviction_key = next(
                (key for key in self._entries if key not in retained_keys),
                next(iter(self._entries)),
            )
            product = self._entries.pop(eviction_key)
            self._usage_bytes -= product.retained_bytes
        self._report()

    def _report(self) -> None:
        """Publish exact retained usage after mutations."""
        if self._usage_changed is not None:
            self._usage_changed(self._usage_bytes)


def _contains_rect(container: QRectF, candidate: QRectF) -> bool:
    """Return whether floating tile geometry fully contains another rectangle."""
    tolerance = 1e-9
    return (
        container.left() <= candidate.left() + tolerance
        and container.top() <= candidate.top() + tolerance
        and container.right() + tolerance >= candidate.right()
        and container.bottom() + tolerance >= candidate.bottom()
    )


def _clip_product_to_request(
    product: RenderTileProduct,
    request: RenderTileRequest,
) -> RenderTileProduct:
    """Return a shared-image presentation view limited to one cold tile core."""
    target = request.source_rect
    if product.source_rect == target:
        return product
    horizontal_scale = product.image_source_rect.width() / product.source_rect.width()
    vertical_scale = product.image_source_rect.height() / product.source_rect.height()
    image_source_rect = QRectF(
        product.image_source_rect.x()
        + (target.x() - product.source_rect.x()) * horizontal_scale,
        product.image_source_rect.y()
        + (target.y() - product.source_rect.y()) * vertical_scale,
        target.width() * horizontal_scale,
        target.height() * vertical_scale,
    )
    return RenderTileProduct(
        product.key,
        target,
        product.image,
        image_source_rect,
    )
