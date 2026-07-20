#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Lease-based lifetime ownership for sources shared by composition instances."""

from __future__ import annotations

from collections import Counter
from enum import Enum
from typing import Protocol

from ..scene.source_references import LayerSourceReference


class ResourceLeaseKind(str, Enum):
    """Reachability roots that can retain a reusable layer source."""

    LIVE = "live"
    SESSION = "session"
    HISTORY = "history"


class CompositionResourceLifecycleOwner(Protocol):
    """Domain owner notified after the final source lease is released."""

    source_type: type[LayerSourceReference]

    def release_unreachable(self, source: LayerSourceReference) -> None:
        """Release domain payload owned by an unreachable source."""
        ...


class CompositionResourceLifetime:
    """Own source reachability counts and final-release domain routing."""

    def __init__(self) -> None:
        """Initialize empty leases and lifecycle-owner routes."""
        self._leases: Counter[tuple[LayerSourceReference, ResourceLeaseKind]] = (
            Counter()
        )
        self._owners: dict[
            type[LayerSourceReference], CompositionResourceLifecycleOwner
        ] = {}

    def register_owner(self, owner: CompositionResourceLifecycleOwner) -> None:
        """Register the sole lifecycle owner for one source-reference type."""
        existing = self._owners.get(owner.source_type)
        if existing is not None and existing is not owner:
            raise ValueError(
                f"resource lifecycle owner already registered: "
                f"{owner.source_type.__name__}"
            )
        self._owners[owner.source_type] = owner

    def unregister_owner(self, owner: CompositionResourceLifecycleOwner) -> None:
        """Remove one lifecycle owner by identity."""
        if self._owners.get(owner.source_type) is owner:
            self._owners.pop(owner.source_type)

    def acquire(
        self,
        source: LayerSourceReference,
        kind: ResourceLeaseKind,
    ) -> None:
        """Retain one source through a named reachability root."""
        self._leases[(source, kind)] += 1

    def release(
        self,
        source: LayerSourceReference,
        kind: ResourceLeaseKind,
    ) -> None:
        """Release one lease and notify the domain after final reachability."""
        key = (source, kind)
        count = self._leases.get(key, 0)
        if count <= 0:
            raise RuntimeError("cannot release an unowned composition resource lease")
        if count == 1:
            self._leases.pop(key, None)
        else:
            self._leases[key] = count - 1
        if self.total_leases(source) == 0:
            owner = self._owners.get(type(source))
            if owner is not None:
                owner.release_unreachable(source)

    def total_leases(self, source: LayerSourceReference) -> int:
        """Return reachability across live, session, and history roots."""
        return sum(
            count
            for (candidate, _kind), count in self._leases.items()
            if candidate == source
        )

    def lease_count(
        self,
        source: LayerSourceReference,
        kind: ResourceLeaseKind,
    ) -> int:
        """Return one source's count for a specific reachability root."""
        return self._leases.get((source, kind), 0)
