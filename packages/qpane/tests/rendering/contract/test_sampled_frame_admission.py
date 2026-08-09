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

"""Contracts for complete sampled-frame admission during source transitions."""

from __future__ import annotations

import uuid

from qpane.rendering.sampled_frame_admission import SampledFrameAdmission


def test_transient_edit_keeps_pending_layer_in_complete_frame_continuity() -> None:
    """Transient patches must retain their base layer until replacement settles."""
    edited_layer = uuid.uuid4()

    admission = SampledFrameAdmission(
        frozenset({edited_layer}),
        frozenset({edited_layer}),
        frozenset(),
        frozenset({edited_layer}),
    )

    assert admission.continuity_layer_ids(frozenset()) == frozenset({edited_layer})


def test_complete_fallback_replaces_pending_layer_without_duplicate_retention() -> None:
    """A complete fallback product supersedes the prior frame for its layer."""
    fallback_layer = uuid.uuid4()

    admission = SampledFrameAdmission(
        frozenset({fallback_layer}),
        frozenset({fallback_layer}),
        frozenset({fallback_layer}),
        frozenset(),
    )

    assert admission.continuity_layer_ids(frozenset({fallback_layer})) == frozenset()


def test_mapping_refinement_keeps_the_current_layer_projection() -> None:
    """Spatial tile demand must not restore a prior transform while pending."""
    transformed_layer = uuid.uuid4()

    admission = SampledFrameAdmission(
        frozenset({transformed_layer}),
        frozenset(),
        frozenset(),
        frozenset({transformed_layer}),
    )

    assert admission.continuity_layer_ids(frozenset()) == frozenset()


def test_pending_layer_without_sampled_product_requests_current_fallback() -> None:
    """A cold sampled batch must use current geometry instead of disappearing."""
    cold_layer = uuid.uuid4()
    admission = SampledFrameAdmission(
        frozenset({cold_layer}),
        frozenset(),
        frozenset(),
        frozenset(),
    )

    assert admission.fallback_candidate_layer_ids == frozenset({cold_layer})
    assert admission.continuity_layer_ids(frozenset({cold_layer})) == frozenset()


def test_fallback_candidates_cover_source_transitions_and_empty_support() -> None:
    """Fallback planning covers new source revisions and unsupported patches."""
    source_transition = uuid.uuid4()
    unsupported_patch = uuid.uuid4()
    admission = SampledFrameAdmission(
        frozenset({source_transition}),
        frozenset({source_transition}),
        frozenset({unsupported_patch}),
        frozenset(),
    )

    assert admission.fallback_candidate_layer_ids == frozenset(
        {source_transition, unsupported_patch}
    )
