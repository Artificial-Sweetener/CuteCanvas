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
"""Public declarative raster, vector, and hybrid scene values."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, TypeAlias, runtime_checkable

from PySide6.QtCore import QPointF, QRectF, QSize
from PySide6.QtGui import QImage

from ..hybrid.model import HybridDocument, HybridPresentationStyle
from ..scene.affine import LayerTransform
from ..scene.mapping import LayerMapping, validate_layer_mapping
from ..scene.model import BlendMode, LayerClip
from ..scene.raster import RasterBounds
from ..scene.source_capabilities import RasterProductPolicy, RasterSourcePatch
from ..vector.model import VectorDocument


@runtime_checkable
class RasterSourceProvider(Protocol):
    """Supply immediately available pixels for one immutable source revision."""

    def image(self, scale: float | None = None) -> QImage | None:
        """Return a detached image, optionally sampled near ``scale``."""
        ...


@runtime_checkable
class SparseRasterSourceProvider(Protocol):
    """Supply bounded sparse patches without materializing transparent gaps."""

    def patches(
        self,
        visible_bounds: RasterBounds,
    ) -> tuple[RasterSourcePatch, ...] | None:
        """Return visible patches or ``None`` to request dense fallback."""
        ...


@runtime_checkable
class RasterHitTestProvider(Protocol):
    """Answer source-local content hit tests for a raster provider."""

    def contains(self, point: QPointF) -> bool:
        """Return whether nontransparent content contains ``point``."""
        ...


class _ImageRasterProvider:
    """Retain one implicitly shared QImage for the simple SDK path."""

    def __init__(self, image: QImage) -> None:
        """Detach the caller's mutable QImage handle."""
        self._image = QImage(image)

    def image(self, scale: float | None = None) -> QImage:
        """Return an implicitly shared detached image handle."""
        del scale
        return QImage(self._image)

    def contains(self, point: QPointF) -> bool:
        """Return whether the point lies over a nontransparent pixel."""
        x = math.floor(point.x())
        y = math.floor(point.y())
        return (
            0 <= x < self._image.width()
            and 0 <= y < self._image.height()
            and self._image.pixelColor(x, y).alpha() > 0
        )


@dataclass(frozen=True, slots=True)
class RasterSource:
    """Describe one reusable revisioned raster source and its provider."""

    source_id: uuid.UUID
    bounds: RasterBounds
    provider: RasterSourceProvider = field(repr=False, compare=False)
    revision: int = 0
    source_kind: str = "raster"
    path: Path | None = None
    product_policy: RasterProductPolicy = RasterProductPolicy.CACHEABLE

    def __post_init__(self) -> None:
        """Validate stable cache identity and provider capability."""
        if self.revision < 0:
            raise ValueError("raster source revision must be non-negative")
        if not self.source_kind.strip():
            raise ValueError("raster source kind must not be empty")
        if not isinstance(self.provider, RasterSourceProvider):
            raise TypeError("provider must implement RasterSourceProvider")
        object.__setattr__(self, "path", None if self.path is None else Path(self.path))
        object.__setattr__(
            self, "product_policy", RasterProductPolicy(self.product_policy)
        )

    @classmethod
    def from_image(
        cls,
        image: QImage,
        *,
        source_id: uuid.UUID | None = None,
        revision: int = 0,
        path: Path | None = None,
        source_kind: str = "image",
    ) -> RasterSource:
        """Create a cacheable source from one non-null QImage.

        Args:
            image: Pixel payload retained through Qt implicit sharing.
            source_id: Optional stable resource identity.
            revision: Non-negative content revision.
            path: Optional originating file path.
            source_kind: Stable render-product namespace.

        Returns:
            Immutable raster source backed by ``image``.
        """
        if not isinstance(image, QImage):
            raise TypeError("image must be QImage")
        if image.isNull():
            raise ValueError("image must not be null")
        return cls(
            source_id=source_id or uuid.uuid4(),
            bounds=RasterBounds(0, 0, image.width(), image.height()),
            provider=_ImageRasterProvider(image),
            revision=revision,
            source_kind=source_kind,
            path=path,
        )

    @property
    def kind(self) -> str:
        """Return the stable source kind used by render products."""
        return self.source_kind

    @property
    def resource_id(self) -> uuid.UUID:
        """Return reusable source identity independently of scene instances."""
        return self.source_id

    @property
    def size(self) -> QSize:
        """Return detached intrinsic source dimensions."""
        return QSize(self.bounds.width, self.bounds.height)


@dataclass(frozen=True, slots=True)
class VectorSource:
    """Describe one immutable semantic vector presentation revision."""

    document: VectorDocument
    presentation_revision: int = 0
    preview_object_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        """Validate the transient presentation generation."""
        if self.presentation_revision < 0:
            raise ValueError("vector presentation revision must be non-negative")

    @property
    def kind(self) -> str:
        """Return the stable semantic vector source kind."""
        return "vector"

    @property
    def resource_id(self) -> uuid.UUID:
        """Return reusable vector resource identity."""
        return self.document.vector_id

    @property
    def revision(self) -> int:
        """Return a scalar render revision for scene invalidation."""
        durable = self.document.revision
        generation = self.presentation_revision
        total = durable + generation
        return total * (total + 1) // 2 + generation

    @property
    def bounds(self) -> RasterBounds:
        """Return intrinsic semantic vector bounds."""
        return self.document.bounds

    @property
    def size(self) -> QSize:
        """Return detached intrinsic vector dimensions."""
        return QSize(self.bounds.width, self.bounds.height)


@dataclass(frozen=True, slots=True)
class HybridSource:
    """Describe one immutable hybrid raster/vector presentation revision."""

    document: HybridDocument
    style: HybridPresentationStyle
    presentation_revision: int = 0

    def __post_init__(self) -> None:
        """Validate the independent presentation generation."""
        if self.presentation_revision < 0:
            raise ValueError("hybrid presentation revision must be non-negative")

    @property
    def kind(self) -> str:
        """Return the stable hybrid source kind."""
        return "hybrid"

    @property
    def resource_id(self) -> uuid.UUID:
        """Return reusable hybrid resource identity."""
        return self.document.source_id

    @property
    def revision(self) -> int:
        """Return a scalar content and presentation revision."""
        durable = self.document.revision
        generation = self.presentation_revision
        total = durable + generation
        return total * (total + 1) // 2 + generation

    @property
    def bounds(self) -> RasterBounds:
        """Return intrinsic hybrid document bounds."""
        return self.document.bounds

    @property
    def size(self) -> QSize:
        """Return detached intrinsic hybrid dimensions."""
        return QSize(self.bounds.width, self.bounds.height)


RenderSource: TypeAlias = RasterSource | VectorSource | HybridSource


@dataclass(frozen=True, slots=True)
class RenderLayer:
    """Place one reusable raster, vector, or hybrid source in a render scene."""

    source: RenderSource
    layer_id: uuid.UUID = field(default_factory=uuid.uuid4)
    transform: LayerMapping = field(default_factory=LayerTransform)
    visible: bool = True
    opacity: float = 1.0
    blend_mode: BlendMode = BlendMode.NORMAL
    clip: LayerClip | None = None
    hit_test: bool = True
    role: str = "content"
    label: str | None = None

    def __post_init__(self) -> None:
        """Validate presentation values without inspecting source pixels."""
        if not isinstance(self.source, (RasterSource, VectorSource, HybridSource)):
            raise TypeError(
                "source must be RasterSource, VectorSource, or HybridSource"
            )
        validate_layer_mapping(self.transform, self.source.bounds)
        if not 0.0 <= self.opacity <= 1.0:
            raise ValueError("layer opacity must be between 0.0 and 1.0")
        object.__setattr__(self, "blend_mode", BlendMode(self.blend_mode))
        object.__setattr__(self, "role", str(self.role))


@dataclass(frozen=True, slots=True)
class RenderScene:
    """Describe one immutable ordered render scene and canvas."""

    canvas: QRectF
    layers: tuple[RenderLayer, ...] = ()
    scene_id: uuid.UUID = field(default_factory=uuid.uuid4)

    def __post_init__(self) -> None:
        """Detach the canvas and reject ambiguous layer identities."""
        canvas = QRectF(self.canvas)
        values = (canvas.x(), canvas.y(), canvas.width(), canvas.height())
        if not all(math.isfinite(value) for value in values):
            raise ValueError("scene canvas values must be finite")
        if canvas.width() <= 0.0 or canvas.height() <= 0.0:
            raise ValueError("scene canvas dimensions must be positive")
        layers = tuple(self.layers)
        layer_ids = tuple(layer.layer_id for layer in layers)
        if len(set(layer_ids)) != len(layer_ids):
            raise ValueError("render scene layer IDs must be unique")
        object.__setattr__(self, "canvas", canvas)
        object.__setattr__(self, "layers", layers)

    @classmethod
    def from_size(
        cls,
        size: QSize,
        layers: tuple[RenderLayer, ...] = (),
        *,
        scene_id: uuid.UUID | None = None,
    ) -> RenderScene:
        """Create a zero-origin scene from one positive canvas size."""
        if not isinstance(size, QSize):
            raise TypeError("size must be QSize")
        return cls(
            QRectF(0.0, 0.0, float(size.width()), float(size.height())),
            layers,
            scene_id or uuid.uuid4(),
        )
