#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Shared Qt image resampling across affine coordinate spaces."""

from __future__ import annotations

from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage, QPainter

from ..scene.affine import LayerTransform
from ..scene.raster import RasterBounds


class AffineImageResampler:
    """Project one bounded raster into explicit destination-coordinate storage."""

    def project(
        self,
        image: QImage,
        *,
        source_bounds: RasterBounds,
        transform: LayerTransform,
        destination_bounds: RasterBounds,
        image_format: QImage.Format,
        smooth: bool = True,
    ) -> QImage:
        """Return pixels mapped from source coordinates into destination bounds."""
        target = QImage(
            destination_bounds.width,
            destination_bounds.height,
            image_format,
        )
        target.fill(0)
        if image.isNull() or not transform.is_invertible:
            return target
        mapped_origin = transform.map_point(
            QPointF(float(source_bounds.x), float(source_bounds.y))
        )
        source_image_to_target = LayerTransform(
            m11=transform.m11,
            m12=transform.m12,
            m21=transform.m21,
            m22=transform.m22,
            dx=mapped_origin.x() - destination_bounds.x,
            dy=mapped_origin.y() - destination_bounds.y,
        )
        painter = QPainter(target)
        try:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, smooth)
            painter.setTransform(source_image_to_target.to_qtransform())
            painter.drawImage(QPointF(0.0, 0.0), image)
        finally:
            painter.end()
        return target
