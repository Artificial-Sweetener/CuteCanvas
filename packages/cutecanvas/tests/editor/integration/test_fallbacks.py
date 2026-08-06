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

import logging

from cutecanvas.core import FeatureFailure, FeatureFallbacks


def test_warning_then_debug_for_additional_context(caplog):
    fallbacks = FeatureFallbacks()
    failure = FeatureFailure(
        message="Optional feature dependency is unavailable.",
        hint="Install the requested feature extra to enable it.",
    )
    fallbacks.record_failure("mask", failure)
    with caplog.at_level(logging.DEBUG, logger="cutecanvas.core.fallbacks"):
        assert fallbacks.get("mask", "initial-context", default=None) is None
        assert fallbacks.get("mask", "secondary-context", default=None) is None
    assert len(caplog.records) == 2
    warning_record, debug_record = caplog.records
    assert warning_record.levelno == logging.WARNING
    assert "Hint:" in warning_record.message
    assert "initial-context" in warning_record.message
    assert debug_record.levelno == logging.DEBUG
    assert "secondary-context" in debug_record.message
    assert "continues with fallback behavior" in debug_record.message


def test_log_once_per_context_emits_warnings_for_each_context(caplog):
    fallbacks = FeatureFallbacks(log_once_per_context=True)
    fallbacks.record_failure("sam", "Failed to import SAM services.")
    with caplog.at_level(logging.WARNING, logger="qpane.core.fallbacks"):
        fallbacks.get("sam", "first-call", default=None)
        fallbacks.get("sam", "second-call", default=None)
    assert [record.levelno for record in caplog.records] == [
        logging.WARNING,
        logging.WARNING,
    ]
    assert all("sam" in record.message for record in caplog.records)


def test_reason_helpers_and_reset():
    fallbacks = FeatureFallbacks()
    assert fallbacks.is_available("sam")
    assert fallbacks.get_reason("sam") is None
    fallbacks.record_failure("sam", "dependency missing")
    assert fallbacks.is_available("sam") is False
    assert fallbacks.get_reason("sam") == "dependency missing"
    snapshot = fallbacks.reasons()
    assert snapshot["sam"] == "dependency missing"
    fallbacks.record_success("sam")
    assert fallbacks.is_available("sam")
    assert fallbacks.get_reason("sam") is None
    fallbacks.reset()
    assert fallbacks.is_available("sam")
    assert "sam" not in fallbacks.reasons()
    assert snapshot["sam"] == "dependency missing"
