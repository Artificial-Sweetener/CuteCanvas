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
"""ViewerApi behavior for the CuteCanvas facade."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QPoint,
    QPointF,
    QRectF,
    QSize,
)
from PySide6.QtGui import (
    QImage,
)
from qpane.sdk.catalog import Catalog, ImageMap
from qpane.sdk.overlays import OverlayDrawFn
from qpane.sdk.rendering import PanelHitTest
from qpane.sdk.types import (
    LinkedGroup,
)

from cutecanvas.core.config import Config
from cutecanvas.editor import (
    EditorOperation,
)
from cutecanvas.masks.workflow import MaskInfo
from cutecanvas.scene.geometry import aspect_scene_rect
from cutecanvas.types import (
    CompositionSnapshot,
    DiagnosticsDomain,
    EditorIntent,
    EditorOperationState,
    EditorPolicy,
)

if TYPE_CHECKING:
    from cutecanvas.masks.mask_undo import MaskUndoState


class ViewerApiMixin:
    """Group viewerapi facade behavior."""

    @staticmethod
    def imageMapFromLists(
        images: Iterable[QImage],
        paths: Iterable[Path | None] | None = None,
        ids: Iterable[uuid.UUID] | None = None,
    ) -> ImageMap:
        """Build an ImageMap of CatalogEntry values from aligned iterables via the shared helper."""
        return Catalog.imageMapFromLists(images, paths=paths, ids=ids)

    @staticmethod
    def fitSceneRect(source_size: QSize, target_rect: QRectF) -> QRectF:
        """Return the largest centered aspect-preserving scene rect inside a target.

        Args:
            source_size: Source image size whose aspect ratio should be preserved.
            target_rect: Scene-coordinate slot that should contain the result.

        Returns:
            A detached ``QRectF`` centered inside ``target_rect``.

        Raises:
            ValueError: If ``source_size`` is empty or ``target_rect`` has
                negative dimensions.
        """
        return aspect_scene_rect(
            source_size,
            target_rect,
            cover=False,
        )

    @staticmethod
    def fillSceneRect(source_size: QSize, target_rect: QRectF) -> QRectF:
        """Return the smallest centered aspect-preserving scene rect covering a target.

        Args:
            source_size: Source image size whose aspect ratio should be preserved.
            target_rect: Scene-coordinate slot that should be covered.

        Returns:
            A detached ``QRectF`` centered on ``target_rect``. The result may
            extend outside ``target_rect``.

        Raises:
            ValueError: If ``source_size`` is empty or ``target_rect`` has
                negative dimensions.
        """
        return aspect_scene_rect(
            source_size,
            target_rect,
            cover=True,
        )

    @property
    def settings(self) -> Config:
        """Expose the active configuration snapshot managed by QPaneState."""
        state = getattr(self, "_state", None)
        if state is None:
            raise AttributeError("CuteCanvas settings accessed before initialization")
        return state.settings

    @settings.setter
    def settings(self, new_settings: Config) -> None:
        """Prevent direct mutation; callers must use applySettings."""
        raise AttributeError(
            "CuteCanvas.settings is read-only; call CuteCanvas.applySettings to change configuration"
        )

    @property
    def installedFeatures(self) -> tuple[str, ...]:
        """Expose the set of features successfully installed on this CuteCanvas."""
        return self._state.installed_features

    def placeholderActive(self) -> bool:
        """Return True when the placeholder policy is active."""
        return self.catalog().placeholderActive()

    @property
    def currentImage(self) -> QImage | None:
        """Return the selected catalog image, or None when absent."""
        catalog = self.catalog()
        return catalog.currentImage()

    @property
    def currentImagePath(self) -> Path | None:
        """Return the filesystem path for the current image, if any."""
        catalog = self.catalog()
        return catalog.currentImagePath()

    @property
    def allImages(self) -> list[QImage]:
        """Return a shallow copy of all original images currently held by this CuteCanvas."""
        catalog = self.catalog()
        return catalog.allImages()

    @property
    def allImagePaths(self) -> list[Path | None]:
        """Return a shallow copy of all file paths associated with images in this CuteCanvas."""
        catalog = self.catalog()
        return catalog.allImagePaths()

    def imagePath(self, image_id: uuid.UUID | None) -> Path | None:
        """Return the filesystem path for ``image_id`` when available."""
        catalog = self.catalog()
        return catalog.imagePath(image_id)

    def currentImageID(self) -> uuid.UUID | None:
        """Return the UUID of the currently selected image via the facade."""
        return self.catalog().currentImageID()

    def imageIDs(self) -> list[uuid.UUID]:
        """Return the ordered image IDs managed by the catalog via the facade."""
        return self.catalog().imageIDs()

    def hasImages(self) -> bool:
        """Return True when the catalog currently contains images."""
        return bool(self.catalog().imageIDs())

    def linkedGroups(self) -> tuple[LinkedGroup, ...]:
        """Return link groups paired with their stable identifiers via the facade."""
        return self.linkManager().getGroupRecords()

    def currentCompositionID(self) -> uuid.UUID | None:
        """Return the active composition UUID."""
        return self.compositionService().current_composition_id()

    def compositionIDs(self) -> list[uuid.UUID]:
        """Return composition UUIDs in browser order."""
        return list(self.compositionService().composition_ids())

    def getCompositionSnapshot(self) -> CompositionSnapshot:
        """Return a structured snapshot of composition browser state."""
        return self.compositionService().snapshot()

    def activeMaskID(self) -> uuid.UUID | None:
        """Return the active mask identifier when masking is available."""
        return self._masks_controller.getActiveMaskID()

    def maskIDsForImage(self, image_id: uuid.UUID | None = None) -> list[uuid.UUID]:
        """Return masks for an image adapter or the active composition."""
        return self._masks_controller.maskIDsForImage(image_id)

    def listMasksForImage(
        self, image_id: uuid.UUID | None = None
    ) -> tuple[MaskInfo, ...]:
        """Return mask rows for an image adapter or the active composition."""
        return self._masks_controller.listMasksForImage(image_id)

    def getActiveMaskImage(self) -> QImage | None:
        """Return the QImage for the currently active mask layer."""
        return self._masks_controller.get_active_mask_image()

    def getMaskUndoState(self, mask_id: uuid.UUID) -> MaskUndoState | None:
        """Expose the current undo/redo depth for ``mask_id`` when available."""
        return self._masks_controller.get_mask_undo_state(mask_id)

    def diagnosticsOverlayEnabled(self) -> bool:
        """Return True when the diagnostics overlay is currently visible."""
        return self.diagnosticsOverlayController().overlayEnabled()

    def diagnosticsDomains(self) -> tuple[str, ...]:
        """Return diagnostics domains that expose detail-tier providers."""
        return self.diagnosticsOverlayController().domains()

    def diagnosticsDomainEnabled(self, domain: str | DiagnosticsDomain) -> bool:
        """Return True when detail-tier diagnostics for ``domain`` are active.

        Raises:
            ValueError: When the requested diagnostics domain is unavailable.
        """
        canonical = self._normalize_diagnostics_domain(domain)
        return self.diagnosticsOverlayController().domainEnabled(canonical)

    def maskFeatureAvailable(self) -> bool:
        """Return True when mask tooling is currently available."""
        return self._masks_controller.mask_feature_available()

    def samFeatureAvailable(self) -> bool:
        """Return True when SAM tooling is currently available."""
        return self._masks_controller.sam_feature_available()

    def samCheckpointReady(self) -> bool:
        """Return True when the SAM checkpoint is available on disk."""
        manager = self._sam_manager
        if manager is None:
            return False
        return manager.checkpointReady()

    def samCheckpointPath(self) -> Path | None:
        """Return the resolved SAM checkpoint path when SAM is available."""
        manager = self._sam_manager
        return None if manager is None else manager.checkpointPath()

    def refreshSamFeature(self) -> tuple[bool, str]:
        """Reinstall SAM tooling using the current configuration snapshot.

        Returns:
            Tuple of (success, message) describing the refresh result.

        Side effects:
            Detaches the active SAM manager and reinstalls the SAM feature.
        """
        if "sam" not in self.installedFeatures:
            return False, "SAM tools disabled in this mode."
        try:
            from qpane.sdk.features import FeatureInstallError

            from cutecanvas.masks.sam_feature import install_sam_feature

            self._masks_controller.detachSamManager()
            install_sam_feature(self)
        except FeatureInstallError as exc:
            hint = f" {exc.hint}" if exc.hint else ""
            return False, f"SAM refresh failed: {exc}.{hint}".strip()
        except Exception as exc:  # noqa: BLE001 - SAM backend boundary
            return False, f"SAM refresh failed: {exc}."
        return True, "SAM refreshed."

    def availableControlModes(self) -> tuple[str, ...]:
        """Return registered control mode identifiers in activation order."""
        return self._tools_manager.available_modes()

    def getControlMode(self) -> str:
        """Return the name of the currently active control mode."""
        return self._tools_manager.get_control_mode()

    def currentZoom(self) -> float:
        """Return the current viewport zoom factor without accessing view internals elsewhere."""
        return float(self.view().viewport.zoom)

    def currentViewportRect(self) -> QRectF:
        """Return the cached physical viewport rectangle reported via ``viewportRectChanged``."""
        rect = self._last_viewport_rect
        return QRectF(rect) if rect is not None else self.physicalViewportRect()

    def setZoomFit(self) -> None:
        """Fit the current content to the viewport and recenter pan."""
        self.view().viewport.setZoomFit()

    def setZoom1To1(self, anchor: QPoint | QPointF | None = None) -> None:
        """Snap zoom to native scale while keeping ``anchor`` steady when provided."""
        self.view().viewport.setZoom1To1(anchor=anchor)

    def applyZoom(
        self,
        requested_zoom: float,
        anchor: QPoint | QPointF | None = None,
    ):
        """Clamp zoom requests and remap unity to the device-native scale.

        Args:
            requested_zoom: Desired zoom multiple in image-space units. Values above 10 are capped,
                and a request of 1.0 is converted to ``viewport.nativeZoom()`` so HiDPI displays
                render one image pixel per physical device pixel.
            anchor: Optional widget-space point to keep stationary while zooming.

        Side effects:
            Logs a warning and returns when no image is loaded or the viewport is locked; otherwise
            forwards the bounded zoom to ``viewport.applyZoom()``.
        """
        new_zoom = self._normalize_zoom_request(requested_zoom)
        if new_zoom is None:
            return
        self.view().viewport.applyZoom(new_zoom, anchor=anchor)

    def panelHitTest(self, panel_pos: QPoint) -> PanelHitTest | None:
        """Return panel hit-test metadata matching ``panel_pos`` when content is available."""
        return self.view().panel_hit_test(panel_pos)

    def applySettings(self, *, config: Config | None = None, **overrides) -> None:
        """Replace the active configuration snapshot and reconfigure services.

        Args:
            config: Optional configuration snapshot to apply.
            overrides: Configuration overrides forwarded to ``QPaneState``.

        Side effects:
            Refreshes mask autosave wiring, marks the view dirty, and schedules a repaint.

        Raises:
            ValueError: When strict config mode is enabled and overrides target
                inactive feature namespaces.
        """
        self._state.apply_settings(config=config, **overrides)
        self.refreshMaskAutosavePolicy()
        self._apply_diagnostics_overlay_preferences()
        self._refresh_screen_tracking()
        self.markDirty()
        self.update()

    def editorPolicy(self) -> EditorPolicy:
        """Return the immutable host capability policy for editor operations."""
        return self._editor_policy.policy

    def setEditorPolicy(self, policy: EditorPolicy) -> bool:
        """Replace independently composable editor capabilities.

        Args:
            policy: Complete immutable host capability policy.

        Returns:
            ``True`` when the policy changed.

        Raises:
            TypeError: If ``policy`` is not ``EditorPolicy``.

        Side effects:
            Cancels provisional gestures losslessly and emits ``editorPolicyChanged``.
        """
        if not isinstance(policy, EditorPolicy):
            raise TypeError("policy must be EditorPolicy")
        if policy == self._editor_policy.policy:
            return False
        self.interaction.cancel_active_editor_input()
        movement = self._editor_movement_interaction
        transform = self._scene_transform_interaction
        painting = self._painting
        if movement is not None:
            movement.cancel()
        if transform is not None:
            transform.cancel()
        if painting is not None:
            painting.cancel()
        changed = self._editor_policy.replace(policy)
        self.refreshCursor()
        self.update()
        return changed

    def editorOperationState(
        self,
        intent: EditorIntent,
        panel_pos: QPoint | QPointF | None = None,
    ) -> EditorOperationState:
        """Resolve one editor intent against current source, selection, and policy.

        Args:
            intent: Operation to inspect without mutating editor state.
            panel_pos: Optional widget position used for Move hit arbitration.

        Returns:
            Detached permission, denial, alternatives, and resolved identities.

        Raises:
            TypeError: If inputs use unsupported public types.
        """
        if not isinstance(intent, EditorIntent):
            raise TypeError("intent must be EditorIntent")
        if panel_pos is not None and not isinstance(panel_pos, (QPoint, QPointF)):
            raise TypeError("panel_pos must be QPoint, QPointF, or None")
        operation = EditorOperation(intent.value)
        scene_point = (
            None
            if panel_pos is None
            else self.view().panel_to_scene_point(QPointF(panel_pos))
        )
        candidate_layer_id = None
        if operation is EditorOperation.MOVE and panel_pos is not None:
            interaction = self._scene_movement_interaction
            candidate = (
                None
                if interaction is None
                else interaction.candidate_at(QPointF(panel_pos))
            )
            candidate_layer_id = None if candidate is None else candidate.hit.layer_id
        resolution = self.editorOperationResolver().resolve(
            operation,
            scene_point=scene_point,
            candidate_layer_id=candidate_layer_id,
        )
        return EditorOperationState(
            intent=intent,
            allowed=resolution.allowed,
            denial=None if resolution.allowed else resolution.denial.value,
            alternatives=tuple(value.value for value in resolution.alternatives),
            scene_id=resolution.scene_id,
            layer_id=resolution.layer_id,
        )

    def setDiagnosticsOverlayEnabled(self, enabled: bool) -> None:
        """Show or hide the diagnostics overlay via its controller."""
        self.diagnosticsOverlayController().setOverlayEnabled(enabled)

    def setDiagnosticsDomainEnabled(
        self, domain: str | DiagnosticsDomain, enabled: bool
    ) -> None:
        """Enable or disable detail-tier diagnostics providers for ``domain``.

        Raises:
            ValueError: When the requested diagnostics domain is unavailable.
        """
        canonical = self._normalize_diagnostics_domain(domain)
        self.diagnosticsOverlayController().setDomainEnabled(canonical, enabled)

    def registerOverlay(
        self,
        name: str,
        draw_fn: OverlayDrawFn,
    ) -> None:
        """Register a content-space overlay to be painted after rendered content.

        Raises:
            ValueError: If `name` is already present.
        """
        self.interaction.registerOverlay(name, draw_fn)

    def unregisterOverlay(self, name: str) -> None:
        """Remove a previously registered overlay.

        Missing entries are ignored so callers can always unregister during teardown.
        """
        self.interaction.unregisterOverlay(name)

    def contentOverlays(self) -> Mapping[str, OverlayDrawFn]:
        """Return a read-only snapshot of registered content overlays."""
        return self.interaction.content_overlays_snapshot()
