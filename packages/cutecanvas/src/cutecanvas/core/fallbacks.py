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

"""Fallback utilities for optional QPane features with context-aware logging."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

logger = logging.getLogger(__name__)


__all__ = ["FeatureFailure", "FeatureFallbacks"]


@dataclass(frozen=True)
class FeatureFailure:
    """Structured failure details recorded for a feature install attempt."""

    message: str
    hint: str | None = None
    cause: BaseException | None = None

    def reason(self) -> str:
        """Return the failure message, defaulting to a placeholder when empty."""
        return self.message if self.message else "no reason provided"

    def formatted(self) -> str:
        """Return the reason string combined with the optional hint."""
        base = self.reason()
        if self.hint:
            return f"{base} Hint: {self.hint}"
        return base


class FeatureFallbacks:
    """Manage fallback behavior and diagnostics for optional integrations.

    Centralize logging for missing features and track contexts that relied on
    fallback results. Calls are expected to originate from the QPane UI thread;
    add external locking before sharing an instance across threads.
    """

    def __init__(self, *, log_once_per_context: bool = False) -> None:
        """Configure the fallback handler with the desired logging policy.

        Args:
            log_once_per_context: When ``True`` emit a warning per unique
                ``(feature, context)`` pair. When ``False``, warnings dedupe per
                feature and additional contexts are logged at ``DEBUG`` level.
        """
        self._log_once_per_context = log_once_per_context
        self._failures: dict[str, FeatureFailure] = {}
        self._warned: set[str | tuple[str, str]] = set()
        self._contexts: dict[str, set[str]] = {}

    def is_available(self, feature: str) -> bool:
        """Return ``True`` when the feature is installed and ready to use."""
        return feature not in self._failures

    def get_reason(self, feature: str) -> str | None:
        """Retrieve the recorded failure reason, if any."""
        failure = self._failures.get(feature)
        return failure.message if failure else None

    def get_failure(self, feature: str) -> FeatureFailure | None:
        """Return the structured failure details for a feature, if recorded."""
        return self._failures.get(feature)

    def reasons(self) -> Mapping[str, str]:
        """Expose an immutable snapshot of all recorded failure reasons."""
        return MappingProxyType({k: v.message for k, v in self._failures.items()})

    def record_failure(self, feature: str, failure: FeatureFailure | str) -> None:
        """Persist the reason a feature could not be activated."""
        if not isinstance(failure, FeatureFailure):
            failure = FeatureFailure(message=str(failure))
        self._failures[feature] = failure

    def record_success(self, feature: str) -> None:
        """Clear failure state once the feature becomes available."""
        self._failures.pop(feature, None)
        self._prune_warned(feature)
        self._contexts.pop(feature, None)

    def get(self, feature: str, context: str, default: Any = None) -> Any:
        """Return ``default`` while emitting diagnostics for missing features."""
        self._ensure_placeholder(feature)
        self._emit(feature, context)
        return default

    def reset(self) -> None:
        """Clear all recorded failures and logging history."""
        self._failures.clear()
        self._warned.clear()
        self._contexts.clear()

    def _ensure_placeholder(self, feature: str) -> None:
        """Guarantee ``feature`` has a recorded failure so logging is consistent."""
        if feature not in self._failures:
            self._failures[feature] = FeatureFailure(message="")

    def _emit(self, feature: str, context: str) -> None:
        """Log a warning/debug message for the fallback context when needed."""
        warn_key = self._warn_key(feature, context)
        contexts = self._contexts.setdefault(feature, set())
        failure = self._failures[feature]
        if warn_key in self._warned:
            if context not in contexts:
                contexts.add(context)
                self._log_debug(feature, failure, context)
            return
        message = self._format_warning(feature, failure, context)
        logger.warning(message)
        self._warned.add(warn_key)
        contexts.add(context)

    def _warn_key(self, feature: str, context: str) -> str | tuple[str, str]:
        """Return the dedupe key based on the current logging policy."""
        if self._log_once_per_context:
            return (feature, context)
        return feature

    def _prune_warned(self, feature: str) -> None:
        """Drop warning keys associated with ``feature`` after success."""
        self._warned = {
            key
            for key in self._warned
            if not (key == feature or (isinstance(key, tuple) and key[0] == feature))
        }

    def _log_debug(self, feature: str, failure: FeatureFailure, context: str) -> None:
        """Emit a debug message summarizing ongoing fallback usage for ``feature``."""
        message = failure.message
        if message:
            logger.debug(
                "Feature '%s' still unavailable (%s); '%s' continues with fallback behavior.",
                feature,
                message,
                context,
            )
        else:
            logger.debug(
                "Feature '%s' still unavailable; '%s' continues with fallback behavior.",
                feature,
                context,
            )

    def _format_warning(
        self, feature: str, failure: FeatureFailure, context: str
    ) -> str:
        """Return the formatted warning string describing the fallback reason and hint."""
        message = failure.message
        if message:
            base = (
                f"Feature '{feature}' unavailable ({message}); "
                f"'{context}' is using fallback behavior."
            )
        else:
            base = (
                f"Feature '{feature}' not installed; "
                f"'{context}' is using fallback behavior."
            )
        if failure.hint:
            return f"{base} Hint: {failure.hint}"
        return base
