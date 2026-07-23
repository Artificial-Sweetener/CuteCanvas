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

"""Execute deterministic abuse traces and preserve evidence on failure."""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import NoReturn

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QCursor, QImage

from .abuse_model import (
    AbuseAction,
    AbuseReport,
    AbuseViolation,
    EditorWorkflowAction,
    HarnessPoint,
    IdleAction,
    MouseHoverAction,
    PalmContactAction,
    PenHoverAction,
    PenLeaveAction,
    PointerKind,
    RedoAction,
    StrokeAction,
    TouchNavigationAction,
    UndoAction,
    WaitAction,
    action_to_dict,
)
from .editor_workflow import MountedEditorWorkflow
from .input_driver import QtStrokeDriver
from .mounted_qpane import MountedQPaneHarness, PresentedMaskFrame
from .release_probe import ReleaseFrame, ReleaseTransitionProbe
from .visual_oracle import StrokeVisualOracle


class _InvariantFailure(RuntimeError):
    """Carry one structured abuse invariant failure to the runner boundary."""

    def __init__(self, violation: AbuseViolation) -> None:
        super().__init__(violation.message)
        self.violation = violation


class MaskAbuseRunner:
    """Coordinate real input, an independent oracle, and failure evidence."""

    def __init__(
        self,
        harness: MountedQPaneHarness,
        *,
        seed: int,
        artifact_directory: Path | None = None,
        feedback_timeout_ms: int = 200,
    ) -> None:
        """Initialize a deterministic session over ``harness``."""
        self._harness = harness
        self._seed = seed
        self._artifact_directory = artifact_directory
        self._feedback_timeout_ms = feedback_timeout_ms
        self._driver = QtStrokeDriver(harness)
        self._oracle = StrokeVisualOracle()
        self._max_feedback_latency_ms = 0.0
        self._current_action_index = -1
        self._before_action = QImage()
        self._release_frames: tuple[ReleaseFrame, ...] = ()

    def run(self, actions: tuple[AbuseAction, ...]) -> AbuseReport:
        """Execute actions until completion or the first invariant violation."""
        try:
            for index, action in enumerate(actions):
                self._current_action_index = index
                self._before_action = self._harness.capture()
                self._release_frames = ()
                self._run_action(action)
        except _InvariantFailure as failure:
            report = AbuseReport(
                seed=self._seed,
                action_count=len(actions),
                completed_actions=self._current_action_index,
                max_feedback_latency_ms=self._max_feedback_latency_ms,
                violation=failure.violation,
            )
            self._write_failure_artifacts(report, actions)
            return report
        return AbuseReport(
            seed=self._seed,
            action_count=len(actions),
            completed_actions=len(actions),
            max_feedback_latency_ms=self._max_feedback_latency_ms,
        )

    def _run_action(self, action: AbuseAction) -> None:
        """Dispatch one typed abuse action."""
        if isinstance(action, StrokeAction):
            self._run_stroke(action)
        elif isinstance(action, UndoAction):
            self._run_undo(action)
        elif isinstance(action, RedoAction):
            self._run_redo(action)
        elif isinstance(action, IdleAction):
            self._run_idle(action)
        elif isinstance(action, WaitAction):
            self._run_wait(action)
        elif isinstance(action, PenLeaveAction):
            self._run_pen_leave()
        elif isinstance(action, TouchNavigationAction):
            self._run_touch_navigation(action)
        elif isinstance(action, PalmContactAction):
            self._run_palm_contact(action)
        elif isinstance(action, PenHoverAction):
            self._run_pen_hover(action)
        elif isinstance(action, MouseHoverAction):
            self._run_mouse_hover(action)
        elif isinstance(action, EditorWorkflowAction):
            self._run_editor_workflow()
        else:  # pragma: no cover - closed union guard
            raise TypeError(f"Unsupported abuse action: {type(action).__name__}")

    def _run_editor_workflow(self) -> None:
        """Require the mounted editor foundation to satisfy its focused invariants."""
        result = MountedEditorWorkflow(self._harness).run()
        self._max_feedback_latency_ms = max(
            self._max_feedback_latency_ms,
            result.max_latency_ms,
        )
        if not result.succeeded:
            self._fail(result.phase, result.message)

    def _run_stroke(self, action: StrokeAction) -> None:
        """Require continuous live feedback and a durable committed stroke."""
        mask_id = self._activate_mask(action.mask_index)
        self._harness.viewer.setBrushSize(action.brush_size)
        history_before = self._harness.viewer.getMaskUndoState(mask_id)
        before_sample = self._harness.capture()
        self._driver.begin(action)
        self._require_feedback(
            action,
            action.points[0].to_qpoint(),
            phase="contact",
            before=before_sample,
        )
        self._require_expected_tint(
            self._points_outside_pointer_preview(
                self._oracle.expected_tinted_points(
                    self._oracle.partial_action(action, 1)
                ),
                action,
                action.points[0].to_qpoint(),
            ),
            phase="contact-continuity",
        )
        for point_index in range(1, len(action.points)):
            before_sample = self._harness.capture()
            self._driver.move(action, point_index)
            self._require_feedback(
                action,
                action.points[point_index].to_qpoint(),
                phase=f"motion-{point_index}",
                before=before_sample,
            )
            self._require_expected_tint(
                self._points_outside_pointer_preview(
                    self._oracle.expected_tinted_points(
                        self._oracle.partial_action(action, point_index + 1)
                    ),
                    action,
                    action.points[point_index].to_qpoint(),
                ),
                phase=f"motion-continuity-{point_index}",
            )
        self._driver.end(action, drain=False)
        release_transition = ReleaseTransitionProbe(self._harness).observe(
            required_points=self._points_outside_pointer_preview(
                self._oracle.expected_tinted_points(
                    self._oracle.partial_action(action, len(action.points))
                ),
                action,
                action.points[-1].to_qpoint(),
            ),
        )
        self._release_frames = release_transition.frames
        if not release_transition.settled:
            self._fail(
                "release-settle",
                "Mask rendering did not become idle after pointer release",
            )
        if (
            release_transition.changed_pixels > 16
            or release_transition.maximum_channel_delta > 8
        ):
            self._fail(
                "release-continuity",
                "Mask pixels flashed during provisional-to-durable release "
                f"({release_transition.changed_pixels} pixels, "
                f"delta={release_transition.maximum_channel_delta})",
            )
        if release_transition.missing_required_point is not None:
            self._fail(
                "release-visibility",
                "An expected mask segment disappeared from the mounted pane "
                "during release",
                point=release_transition.missing_required_point,
            )
        if action.device is PointerKind.TOUCH:
            self._require_brush_cursor(
                phase="touch-release-cursor",
                missing_message=(
                    "Touch release left CuteCanvas's owned cursor blank before mouse input"
                ),
            )
        history_after = self._harness.viewer.getMaskUndoState(mask_id)
        if history_before is None or history_after is None:
            self._fail(
                "commit",
                "Stroke history state became unavailable during commit",
            )
        changed_mask = history_after != history_before
        if changed_mask and (
            history_after.undo_depth != history_before.undo_depth + 1
            or history_after.redo_depth != 0
        ):
            self._fail(
                "commit",
                "Stroke produced an invalid undo/redo transition",
            )
        if changed_mask:
            self._oracle.commit(action)
        committed_points = self._oracle.expected_tinted_points()
        if action.device is PointerKind.PEN:
            committed_points = self._points_outside_pointer_preview(
                committed_points,
                action,
                action.points[-1].to_qpoint(),
            )
        self._require_expected_tint(
            committed_points,
            phase="committed",
        )

    def _run_undo(self, action: UndoAction) -> None:
        """Require public undo to restore the oracle's previous composition."""
        mask_id = self._activate_mask(action.mask_index)
        state = self._harness.viewer.getMaskUndoState(mask_id)
        if state is None or state.undo_depth == 0:
            self._fail("undo", f"Mask {action.mask_index} has no undo history")
        with self._harness.observe_presented_frames() as frame_probe:
            if not self._harness.viewer.undoMaskEdit():
                self._fail("undo", "CuteCanvas rejected an undo with available history")
            removed = self._oracle.undo(action.mask_index)
            if not self._wait_for_history_state(
                mask_id,
                undo_depth=state.undo_depth - 1,
                redo_depth=state.redo_depth + 1,
            ):
                self._fail("undo", "Undo history depths did not settle as expected")
            self._harness.viewer.repaint()
        expected_points = self._oracle.expected_tinted_points()
        exposed_points = self._oracle.exposed_points_after_removal(removed)
        self._require_valid_history_frames(
            tuple(frame_probe.frames),
            expected_points=expected_points,
            background_points=exposed_points,
            phase="undo-frame",
        )
        self._require_expected_tint(
            expected_points,
            phase="undo-preservation",
        )
        self._require_background(
            exposed_points,
            phase="undo-removal",
        )

    def _run_redo(self, action: RedoAction) -> None:
        """Require public redo to restore the independently expected stroke."""
        mask_id = self._activate_mask(action.mask_index)
        state = self._harness.viewer.getMaskUndoState(mask_id)
        if state is None or state.redo_depth == 0:
            self._fail("redo", f"Mask {action.mask_index} has no redo history")
        with self._harness.observe_presented_frames() as frame_probe:
            if not self._harness.viewer.redoMaskEdit():
                self._fail("redo", "CuteCanvas rejected a redo with available history")
            self._oracle.redo(action.mask_index)
            if not self._wait_for_history_state(
                mask_id,
                undo_depth=state.undo_depth + 1,
                redo_depth=state.redo_depth - 1,
            ):
                self._fail("redo", "Redo history depths did not settle as expected")
            self._harness.viewer.repaint()
        expected_points = self._oracle.expected_tinted_points()
        self._require_valid_history_frames(
            tuple(frame_probe.frames),
            expected_points=expected_points,
            background_points=(),
            phase="redo-frame",
        )
        self._require_expected_tint(
            expected_points,
            phase="redo-restoration",
        )

    def _run_idle(self, action: IdleAction) -> None:
        """Require a settled widget composition to remain pixel-identical."""
        before = self._harness.capture()
        self._harness.drain_events(wait_ms=action.wait_ms)
        after = self._harness.capture()
        if before != after:
            self._fail("idle", "Mounted CuteCanvas pixels changed without new input")
        self._require_expected_tint(
            self._oracle.expected_tinted_points(),
            phase="idle-preservation",
        )

    def _run_wait(self, action: WaitAction) -> None:
        """Advance policy time while preserving semantic stroke coverage."""
        self._harness.drain_events(wait_ms=action.wait_ms)
        self._require_expected_tint(
            self._oracle.expected_tinted_points(),
            phase="wait-preservation",
        )

    def _run_pen_leave(self) -> None:
        """End stylus proximity and require all committed mask pixels to remain."""
        self._driver.leave_pen_proximity()
        self._require_expected_tint(
            self._oracle.expected_tinted_points(),
            phase="pen-leave-preservation",
        )

    def _run_touch_navigation(self, action: TouchNavigationAction) -> None:
        """Require second-finger takeover to navigate without committing paint."""
        mask_id = self._activate_mask(action.mask_index)
        history_before = self._harness.viewer.getMaskUndoState(mask_id)
        self._harness.viewer.setZoom1To1(QPoint(250, 250))
        self._harness.drain_events()
        zoom_before = self._harness.viewer.currentZoom()
        pan_before = self._harness.viewer.getPan()

        self._driver.begin_touch_navigation(action)
        self._require_mask_feedback(
            action.primary_start.to_qpoint(), phase="touch-preview"
        )
        self._driver.add_secondary_touch(action)
        rollback = self._harness.wait_for_background(
            action.primary_start.to_qpoint(),
            timeout_ms=self._feedback_timeout_ms,
        )
        if rollback.latency_ms is None:
            self._fail(
                "touch-takeover",
                "Second touch did not roll back provisional paint",
                point=action.primary_start.to_qpoint(),
                color=rollback.color,
            )

        self._driver.move_touch_navigation(action)
        zoom_after = self._harness.viewer.currentZoom()
        pan_after = self._harness.viewer.getPan()
        if abs(zoom_after - zoom_before) < 1e-6:
            self._fail("touch-pinch", "Two-finger pinch did not change zoom")
        if pan_after == pan_before:
            self._fail("touch-pan", "Two-finger translation did not change pan")
        self._driver.end_touch_navigation(action)
        self._require_brush_cursor(
            phase="touch-navigation-release-cursor",
            missing_message="Touch navigation left CuteCanvas's owned cursor blank",
        )

        history_after = self._harness.viewer.getMaskUndoState(mask_id)
        if history_after != history_before:
            self._fail("touch-history", "Touch navigation committed mask history")
        self._harness.viewer.setZoomFit()
        self._harness.drain_events()
        self._require_expected_tint(
            self._oracle.expected_tinted_points(),
            phase="touch-navigation-preservation",
        )

    def _run_palm_contact(self, action: PalmContactAction) -> None:
        """Require active-pen palm rejection to suppress mask mutation."""
        mask_id = self._activate_mask(action.mask_index)
        history_before = self._harness.viewer.getMaskUndoState(mask_id)
        self._driver.send_palm_contact(action)
        background = self._harness.wait_for_background(
            action.point.to_qpoint(),
            timeout_ms=self._feedback_timeout_ms,
        )
        if background.latency_ms is None:
            self._fail(
                "palm-rejection",
                "Touch painted while active-pen palm rejection was engaged",
                point=action.point.to_qpoint(),
                color=background.color,
            )
        if self._harness.viewer.getMaskUndoState(mask_id) != history_before:
            self._fail("palm-history", "Rejected palm contact changed undo history")

    def _run_pen_hover(self, action: PenHoverAction) -> None:
        """Require a hover-capable stylus to draw a non-mutating brush outline."""
        mask_id = self._activate_mask(action.mask_index)
        self._harness.viewer.setBrushSize(action.brush_size)
        history_before = self._harness.viewer.getMaskUndoState(mask_id)
        before = self._harness.capture()
        self._driver.hover_pen(action)
        after = self._harness.capture()
        radius = action.brush_size * self._harness.viewer.currentZoom() / 2.0
        center = action.point.to_qpoint()
        margin = int(radius + 8.0)
        changed_pixels = 0
        for y_position in range(
            max(0, center.y() - margin),
            min(after.height(), center.y() + margin + 1),
        ):
            for x_position in range(
                max(0, center.x() - margin),
                min(after.width(), center.x() + margin + 1),
            ):
                if before.pixel(x_position, y_position) != after.pixel(
                    x_position, y_position
                ):
                    changed_pixels += 1
        if changed_pixels < 8:
            self._fail(
                "pen-hover",
                "Hover-capable stylus did not present a visible brush outline",
                point=center,
                color=after.pixelColor(center),
            )
        if self._harness.viewer.getMaskUndoState(mask_id) != history_before:
            self._fail("pen-hover-history", "Stylus hover changed undo history")
        self._require_expected_tint(
            self._oracle.expected_tinted_points(),
            phase="pen-hover-preservation",
        )

    def _run_mouse_hover(self, action: MouseHoverAction) -> None:
        """Require genuine mouse motion to restore a high-contrast brush cursor."""
        self._driver.hover_mouse(action)
        self._require_brush_cursor(
            phase="mouse-cursor",
            missing_message="Mouse motion did not retain a brush cursor",
        )

    def _require_brush_cursor(self, *, phase: str, missing_message: str) -> None:
        """Require matching brush feedback at QWidget and effective QWindow levels."""
        window = self._harness.host.windowHandle()
        if window is None:
            self._fail(phase, "Mounted CuteCanvas host has no effective Qt window")
        self._validate_brush_cursor(
            self._harness.viewer.cursor(),
            phase=phase,
            missing_message=missing_message,
        )
        self._validate_brush_cursor(
            window.cursor(),
            phase=phase,
            missing_message=f"Effective Qt window cursor is missing: {missing_message}",
        )

    def _validate_brush_cursor(
        self,
        cursor: QCursor,
        *,
        phase: str,
        missing_message: str,
    ) -> None:
        """Require one cursor value to be a centered dual-tone brush."""
        cursor_image = cursor.pixmap().toImage()
        if cursor_image.isNull():
            self._fail(phase, missing_message)
        expected_hotspot = QPoint(cursor_image.width() // 2, cursor_image.height() // 2)
        if cursor.hotSpot() != expected_hotspot:
            self._fail(
                phase,
                "Brush cursor is not centered on the paint point",
            )
        opaque_values = [
            cursor_image.pixelColor(x_position, y_position).value()
            for y_position in range(cursor_image.height())
            for x_position in range(cursor_image.width())
            if cursor_image.pixelColor(x_position, y_position).alpha() >= 128
        ]
        if not opaque_values or min(opaque_values) > 32 or max(opaque_values) < 223:
            self._fail(
                phase,
                "Brush cursor lacks a high-contrast outline",
            )

    def _activate_mask(self, mask_index: int):
        """Activate an action mask and convert index errors into evidence."""
        try:
            return self._harness.activate_mask(mask_index)
        except (IndexError, RuntimeError) as exc:
            self._fail("activate-mask", str(exc))

    def _require_feedback(
        self,
        action: StrokeAction,
        point: QPoint,
        *,
        phase: str,
        before: QImage,
    ) -> None:
        """Require one contact sample to appear within the latency budget."""
        if self._pen_preview_covers_contact(action):
            self._require_visible_pen_preview(point, phase=phase, before=before)
            return
        self._require_mask_feedback(point, phase=phase)
        if action.device is PointerKind.TOUCH:
            self._require_visible_touch_preview(
                action,
                point,
                phase=phase,
            )

    def _require_mask_feedback(self, point: QPoint, *, phase: str) -> None:
        """Require saturated mask feedback at one unobscured contact sample."""
        measurement = self._harness.wait_for_mask_tint(
            point,
            timeout_ms=self._feedback_timeout_ms,
        )
        if measurement.latency_ms is None:
            self._fail(
                phase,
                "Mask feedback did not become visible before the deadline",
                point=point,
                color=measurement.color,
            )
        self._max_feedback_latency_ms = max(
            self._max_feedback_latency_ms,
            measurement.latency_ms,
        )

    def _require_visible_touch_preview(
        self,
        action: StrokeAction,
        point: QPoint,
        *,
        phase: str,
    ) -> None:
        """Require the direct-touch brush-size outline in mounted pixels."""
        tool = self._harness.viewer._tools_manager.get_active_tool()
        preview = getattr(tool, "pointer_preview", None)
        if preview is None or not preview.contact:
            self._fail(
                f"{phase}-touch-cursor",
                "Touch contact did not retain brush preview state",
                point=point,
            )
        after = self._harness.capture()
        viewer = self._harness.viewer
        radius = (
            action.brush_size
            * viewer.currentZoom()
            / (2.0 * max(0.01, viewer.devicePixelRatioF()))
        )
        band = 5.0
        extent = max(6, math.ceil(radius + band + 1.0))
        dark_pixels = 0
        bright_pixels = 0
        for y_position in range(
            max(0, point.y() - extent),
            min(after.height(), point.y() + extent + 1),
        ):
            for x_position in range(
                max(0, point.x() - extent),
                min(after.width(), point.x() + extent + 1),
            ):
                distance = math.hypot(
                    x_position - point.x(),
                    y_position - point.y(),
                )
                if not radius - band <= distance <= radius + band:
                    continue
                color = after.pixelColor(x_position, y_position)
                channels = (color.red(), color.green(), color.blue())
                if max(channels) - min(channels) > 12:
                    continue
                dark_pixels += color.value() <= 80
                bright_pixels += color.value() >= 180
        if dark_pixels < 4 or bright_pixels < 4:
            self._fail(
                f"{phase}-touch-cursor",
                "Touch brush preview was not visibly dual-tone "
                f"(dark={dark_pixels}, bright={bright_pixels})",
                point=point,
                color=after.pixelColor(point),
            )

    def _pen_preview_covers_contact(self, action: StrokeAction) -> bool:
        """Return whether the stylus outline physically covers the painted center."""
        if action.device is not PointerKind.PEN:
            return False
        settings = self._harness.viewer.settings
        minimum_ratio = min(
            1.0,
            max(0.01, float(settings.pen_pressure_min_ratio)),
        )
        gamma = max(0.01, float(settings.pen_pressure_gamma))
        pressure = min(1.0, max(0.0, action.pressure))
        pressure_ratio = minimum_ratio + (1.0 - minimum_ratio) * pressure**gamma
        displayed_diameter = (
            action.brush_size
            * pressure_ratio
            * self._harness.viewer.currentZoom()
            / max(0.01, self._harness.viewer.devicePixelRatioF())
        )
        return displayed_diameter <= 7.0

    def _require_visible_pen_preview(
        self,
        point: QPoint,
        *,
        phase: str,
        before: QImage,
    ) -> None:
        """Require a visible local preview delta for a tiny pen dab."""
        started_at = time.perf_counter()
        deadline = started_at + self._feedback_timeout_ms / 1000.0
        while time.perf_counter() < deadline:
            image = self._harness.capture()
            coordinates = [
                (x_position, y_position)
                for y_position in range(max(0, point.y() - 6), point.y() + 7)
                for x_position in range(max(0, point.x() - 6), point.x() + 7)
                if x_position < image.width() and y_position < image.height()
            ]
            changed_pixels = sum(
                image.pixel(x_position, y_position)
                != before.pixel(x_position, y_position)
                for x_position, y_position in coordinates
            )
            values = [
                image.pixelColor(x_position, y_position).value()
                for x_position, y_position in coordinates
            ]
            if changed_pixels >= 4 or (values and min(values) <= 32):
                latency_ms = (time.perf_counter() - started_at) * 1000.0
                self._max_feedback_latency_ms = max(
                    self._max_feedback_latency_ms,
                    latency_ms,
                )
                return
            self._harness.drain_events(wait_ms=1)
        self._fail(
            phase,
            "Tiny pen contact presented neither visible paint nor its brush outline",
            point=point,
            color=self._harness.color_at(point),
        )

    def _require_expected_tint(
        self,
        points: tuple[QPoint, ...],
        *,
        phase: str,
    ) -> None:
        """Require every independent interior sample to remain visible."""
        image = self._harness.capture()
        for point in points:
            color = image.pixelColor(point)
            if not self._harness.is_mask_tint(color):
                self._fail(
                    phase,
                    "An expected mask segment is absent from mounted pixels",
                    point=point,
                    color=color,
                )

    def _require_valid_history_frames(
        self,
        frames: tuple[PresentedMaskFrame, ...],
        *,
        expected_points: tuple[QPoint, ...],
        background_points: tuple[QPoint, ...],
        phase: str,
    ) -> None:
        """Require every presented history frame to match the semantic result."""
        if not frames:
            self._fail(phase, "History operation presented no observable frame")
        for frame_index, frame in enumerate(frames):
            if expected_points and frame.mask_layer_count == 0:
                self._fail(
                    phase,
                    f"History frame {frame_index} omitted every mask render item",
                )
            for point in expected_points:
                color = frame.color_at(point)
                if not self._harness.is_mask_tint(color):
                    self._fail(
                        phase,
                        f"History frame {frame_index} blinked a retained mask segment",
                        point=point,
                        color=color,
                    )
            for point in background_points:
                color = frame.color_at(point)
                if not self._harness.is_background(color):
                    self._fail(
                        phase,
                        f"History frame {frame_index} retained an undone mask segment",
                        point=point,
                        color=color,
                    )

    def _require_background(
        self,
        points: tuple[QPoint, ...],
        *,
        phase: str,
    ) -> None:
        """Require safely exposed samples to return to the source background."""
        if not points:
            return
        deadline = time.perf_counter() + self._feedback_timeout_ms / 1000.0
        image = self._harness.capture()
        missing = [
            point
            for point in points
            if not self._harness.is_background(image.pixelColor(point))
        ]
        while missing and time.perf_counter() < deadline:
            self._harness.drain_events(wait_ms=1)
            image = self._harness.capture()
            missing = [
                point
                for point in points
                if not self._harness.is_background(image.pixelColor(point))
            ]
        if not missing:
            return
        point = missing[0]
        self._fail(
            phase,
            "Undo left mask tint in an independently exposed region",
            point=point,
            color=image.pixelColor(point),
        )

    def _points_outside_pointer_preview(
        self,
        points: tuple[QPoint, ...],
        action: StrokeAction,
        pointer_position: QPoint,
    ) -> tuple[QPoint, ...]:
        """Exclude pixels that the visible brush outline may legitimately cover."""
        preview_radius = (
            action.brush_size * self._harness.viewer.currentZoom() / 2.0 + 6.0
        )
        radius_squared = preview_radius * preview_radius
        return tuple(
            point
            for point in points
            if (point.x() - pointer_position.x()) ** 2
            + (point.y() - pointer_position.y()) ** 2
            > radius_squared
        )

    def _wait_for_history_state(
        self,
        mask_id,
        *,
        undo_depth: int,
        redo_depth: int,
    ) -> bool:
        """Wait until public undo/redo depths match the expected transition."""
        deadline = time.perf_counter() + self._feedback_timeout_ms / 1000.0
        while time.perf_counter() < deadline:
            self._harness.drain_events(wait_ms=1)
            state = self._harness.viewer.getMaskUndoState(mask_id)
            if (
                state is not None
                and state.undo_depth == undo_depth
                and state.redo_depth == redo_depth
            ):
                return True
        return False

    def _fail(
        self,
        phase: str,
        message: str,
        *,
        point: QPoint | None = None,
        color: QColor | None = None,
    ) -> NoReturn:
        """Raise one structured invariant failure."""
        raise _InvariantFailure(
            AbuseViolation(
                action_index=self._current_action_index,
                phase=phase,
                message=message,
                point=None if point is None else HarnessPoint(point.x(), point.y()),
                color=None if color is None else color.getRgb(),
            )
        )

    def _write_failure_artifacts(
        self,
        report: AbuseReport,
        actions: tuple[AbuseAction, ...],
    ) -> None:
        """Persist replayable evidence when an artifact directory is configured."""
        if self._artifact_directory is None:
            return
        directory = self._artifact_directory / f"seed-{self._seed}"
        directory.mkdir(parents=True, exist_ok=True)
        current = self._harness.capture()
        self._before_action.save(str(directory / "before.png"))
        current.save(str(directory / "current.png"))
        self._difference_image(self._before_action, current).save(
            str(directory / "difference.png")
        )
        for index, frame in enumerate(self._release_frames):
            frame.image.save(
                str(directory / f"release-{index:03d}-{frame.elapsed_ms:08.2f}ms.png")
            )
            frame.mask_render.save(
                str(
                    directory
                    / f"release-mask-{index:03d}-{frame.elapsed_ms:08.2f}ms.png"
                )
            )
        (directory / "trace.json").write_text(
            json.dumps(
                {
                    "seed": self._seed,
                    "actions": [action_to_dict(action) for action in actions],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        payload = report.to_dict()
        payload["diagnostics"] = [
            {"label": label, "value": value}
            for label, value in self._harness.diagnostics_rows()
        ]
        (directory / "report.json").write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _difference_image(before: QImage, after: QImage) -> QImage:
        """Create a high-contrast pixel-change image for failure inspection."""
        width = min(before.width(), after.width())
        height = min(before.height(), after.height())
        difference = QImage(width, height, QImage.Format.Format_RGB32)
        difference.fill(QColor(0, 0, 0))
        for y_position in range(height):
            for x_position in range(width):
                if before.pixel(x_position, y_position) != after.pixel(
                    x_position, y_position
                ):
                    difference.setPixelColor(x_position, y_position, QColor(255, 0, 0))
        return difference
