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

"""Retry controllers that coalesce executor submissions and apply backoff.

The module keeps the scheduling logic reusable so managers can use Qt timers
in production while tests rely on lightweight schedulers.
"""

from __future__ import annotations

import hashlib
import logging
import random
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from time import monotonic
from typing import (
    Generic,
    Protocol,
    TypeVar,
)

from PySide6.QtCore import QCoreApplication, QObject, QThread, QTimer

from .executor import TaskHandle, TaskRejected

logger = logging.getLogger(__name__)

K = TypeVar("K")
P = TypeVar("P")


class RetrySchedulingError(RuntimeError):
    """Raised when retry scheduling cannot be enqueued on the main thread."""


@dataclass(frozen=True)
class RetryContext(Generic[K, P]):
    """Carry retry metadata shared with backoff and termination policies.

    The context avoids Qt objects so tests stay lightweight.
    """

    category: str
    device: str | None
    key: K
    payload_size: int | None = None


class BackoffPolicy:
    """Compute exponential backoff delays with optional deterministic jitter."""

    def __init__(self, base_ms: int, max_ms: int, jitter_pct: float = 0.25) -> None:
        """Configure the exponential backoff parameters.

        Args:
            base_ms: Initial retry delay in milliseconds.
            max_ms: Maximum delay cap applied to later attempts.
            jitter_pct: Fraction of the computed delay used for random jitter.

        Raises:
            ValueError: If ``base_ms`` or ``max_ms`` is not positive.
        """
        if base_ms <= 0 or max_ms <= 0:
            raise ValueError("base_ms and max_ms must be positive")
        self.base_ms = base_ms
        self.max_ms = max_ms
        self.jitter_pct = max(0.0, float(jitter_pct))

    def nextDelayMs(
        self, attempt: int, context: RetryContext[K, P] | None = None
    ) -> int:
        """Return the delay for the supplied retry attempt.

        Args:
            attempt: Ordinal where 1 represents the first retry after submission.
            context: Optional metadata used to derive deterministic jitter.

        Returns:
            Milliseconds to wait before performing the attempt.
        """
        n = max(1, int(attempt))
        base = min(self.max_ms, self.base_ms * (2 ** (n - 1)))
        jitter_cap = min(self.base_ms, int(base * self.jitter_pct))
        if jitter_cap <= 0:
            jitter = 0
        else:
            if context is None:
                jitter = random.randint(0, jitter_cap)
            else:
                # Use a stable digest so jitter is deterministic across runs
                payload_key = repr(context.key)
                device_key = context.device or ""
                data = f"{context.category}|{device_key}|{payload_key}|{n}".encode()
                digest = hashlib.sha1(data).digest()
                seed_val = int.from_bytes(digest[:4], byteorder="big", signed=False)
                rng = random.Random(seed_val)
                jitter = rng.randint(0, jitter_cap)
        delay = base + jitter
        return min(self.max_ms, max(self.base_ms, delay))


@dataclass(frozen=True)
class TerminationPolicy(Generic[K, P]):
    """Control when to stop scheduling retries.

    Attributes:
        attempt_cap: Maximum retry attempts (1 allows one retry) or ``None``.
        time_budget_ms: Optional elapsed-time budget counted from first scheduling.
        should_give_up: Optional predicate that short-circuits the built-in caps.
    """

    attempt_cap: int | None = None
    time_budget_ms: int | None = None
    should_give_up: Callable[[int, RetryContext[K, P]], bool] | None = None

    def shouldGiveUp(
        self,
        attempt: int,
        *,
        started_at: float,
        now: float,
        context: RetryContext[K, P] | None = None,
    ) -> bool:
        """Check attempt counts, elapsed time, and predicates.

        Args:
            attempt: Attempt ordinal currently being scheduled.
            started_at: Monotonic timestamp captured during the first retry.
            now: Current monotonic timestamp.
            context: Optional retry metadata passed to ``should_give_up``.

        Returns:
            True when a cap is exceeded or the predicate signals give-up.
        """
        if self.should_give_up and context is not None:
            try:
                if self.should_give_up(attempt, context):
                    return True
            except Exception:
                logger.debug("should_give_up predicate failed", exc_info=True)
        if self.attempt_cap is not None and attempt > max(0, int(self.attempt_cap)):
            return True
        return bool(
            self.time_budget_ms is not None
            and (now - started_at) * 1000.0 > self.time_budget_ms
        )


@dataclass(frozen=True)
class RetryPolicy(Generic[K, P]):
    """Bundle backoff and termination policies for retry controllers."""

    backoff: BackoffPolicy
    termination: TerminationPolicy[K, P] | None = None

    def nextDelayMs(
        self, attempt: int, context: RetryContext[K, P] | None = None
    ) -> int:
        """Delegate delay calculation to the configured backoff policy.

        Args:
            attempt: Attempt ordinal currently being scheduled.
            context: Optional retry metadata forwarded to the backoff policy.

        Returns:
            Milliseconds to wait before the attempt.
        """
        return self.backoff.nextDelayMs(attempt, context)

    def shouldGiveUp(
        self,
        attempt: int,
        *,
        started_at: float,
        now: float,
        context: RetryContext[K, P] | None = None,
    ) -> bool:
        """Ask the termination policy whether retries should end.

        Args:
            attempt: Attempt ordinal being considered.
            started_at: Timestamp from the first retry scheduling.
            now: Current monotonic timestamp.
            context: Optional metadata forwarded to the termination policy.

        Returns:
            True when no further retries should be scheduled.
        """
        if self.termination is None:
            return False
        return self.termination.shouldGiveUp(
            attempt, started_at=started_at, now=now, context=context
        )


class SchedulerHandle(Protocol):  # pragma: no cover - structural typing only
    """Interface for handles returned by :class:`Scheduler`."""

    def stop(self) -> None:
        """Stop the scheduled callback before it fires."""
        ...

    def deleteLater(self) -> None:
        """Schedule deferred cleanup for the handle when the event loop is idle."""
        ...


class Scheduler(Protocol):
    """Abstracts timer scheduling so tests don't depend on Qt timers."""

    def schedule(
        self, key: K, delay_ms: int, callback: Callable[[], None]
    ) -> SchedulerHandle:
        """Schedule ``callback`` to run after ``delay_ms`` milliseconds."""
        ...

    def cancel(self, handle: SchedulerHandle) -> None:
        """Cancel a previously scheduled callback."""
        ...


class _ProxyTimerHandle:
    """Cancelable proxy for timers created after a main-thread dispatch."""

    def __init__(self) -> None:
        """Initialise proxy state until a real QTimer is attached."""
        self._timer: QTimer | None = None
        self._cancelled: bool = False
        self._delete_requested: bool = False

    @property
    def cancelled(self) -> bool:
        """Return True after stop() is called, regardless of timer attachment."""
        return self._cancelled

    def attach(self, timer: QTimer) -> None:
        """Bind the real timer once created on the main thread."""
        if self._timer is not None:
            return
        self._timer = timer
        if self._cancelled:
            try:
                timer.stop()
                timer.deleteLater()
            except Exception:  # pragma: no cover - defensive guard
                logger.debug(
                    "Failed to dispose timer after early cancel", exc_info=True
                )
            return
        if self._delete_requested:
            try:
                timer.deleteLater()
            except Exception:  # pragma: no cover - defensive guard
                logger.debug(
                    "Failed to delete timer after deferred request", exc_info=True
                )

    def stop(self) -> None:
        """Stop the timer if present and mark the handle as cancelled."""
        self._cancelled = True
        timer = self._timer
        if timer is None:
            return
        try:
            timer.stop()
        except Exception:  # pragma: no cover - defensive guard
            logger.debug("Failed to stop timer handle", exc_info=True)

    def deleteLater(self) -> None:
        """Request deferred deletion for the real timer once attached."""
        timer = self._timer
        if timer is None:
            self._delete_requested = True
            return
        try:
            timer.deleteLater()
        except Exception:  # pragma: no cover - defensive guard
            logger.debug("Failed to delete timer handle", exc_info=True)


class QtTimerScheduler(Scheduler):
    """Scheduler backed by QTimer single-shot timers with main-thread enforcement."""

    def __init__(
        self,
        parent: QObject,
        *,
        dispatcher: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        """Store the QObject parent and optional main-thread dispatcher.

        Args:
            parent: QObject used as the parent for all scheduled timers.
            dispatcher: Optional callable that enqueues callbacks on the Qt main thread.
        """
        self._parent = parent
        self._dispatcher = dispatcher

    def schedule(
        self, key: K, delay_ms: int, callback: Callable[[], None]
    ) -> SchedulerHandle:
        """Schedule ``callback`` after ``delay_ms`` milliseconds, dispatching to the Qt main thread when needed.

        Args:
            key: Key associated with the scheduled retry entry.
            delay_ms: Delay expressed in milliseconds.
            callback: Callable executed once the timer fires.

        Returns:
            A cancelable handle for the scheduled callback, even when dispatching.
        """
        app = QCoreApplication.instance()
        main_thread = app.thread() if app else None
        if main_thread is None:
            logger.error(
                "Failed to schedule retry timer: no QApplication main thread available"
            )
            raise RetrySchedulingError(
                "Retry timer scheduling requires a QApplication main thread"
            )
        if QThread.currentThread() == main_thread:
            return self._start_timer(callback, delay_ms)
        dispatcher = self._dispatcher
        proxy = _ProxyTimerHandle()

        def _start_on_main() -> None:
            """Start the retry timer on the Qt main thread unless cancelled."""
            if proxy.cancelled:
                return
            timer = self._start_timer(callback, delay_ms)
            proxy.attach(timer)

        if callable(dispatcher):
            try:
                dispatcher(_start_on_main)
                return proxy
            except Exception:  # pragma: no cover - defensive guard
                logger.debug(
                    "dispatch_to_main_thread failed; falling back to queued singleShot",
                    exc_info=True,
                )
        try:
            QTimer.singleShot(0, self._parent, _start_on_main)
            return proxy
        except (RuntimeError, TypeError):
            logger.error(
                "Failed to schedule retry timer on main thread; dispatcher missing or failed"
            )
            proxy.stop()
            return proxy

    def cancel(self, handle: SchedulerHandle) -> None:
        """Stop and delete the provided timer handle.

        Args:
            handle: QTimer handle returned by ``schedule``.
        """
        app = QCoreApplication.instance()
        main_thread = app.thread() if app else None
        if isinstance(handle, _ProxyTimerHandle):
            handle.stop()
        if main_thread is None or handle is None:
            return
        if QThread.currentThread() == main_thread:
            self._stop_timer(handle)
            return
        dispatcher = self._dispatcher
        if callable(dispatcher):
            try:
                dispatcher(lambda: self._stop_timer(handle))
                return
            except Exception:  # pragma: no cover - defensive guard
                logger.debug(
                    "dispatch_to_main_thread failed during cancel; falling back",
                    exc_info=True,
                )
        try:
            QTimer.singleShot(0, self._parent, lambda: self._stop_timer(handle))
        except (RuntimeError, TypeError):
            logger.error("Failed to cancel retry timer on main thread; handle may leak")

    def _start_timer(self, callback: Callable[[], None], delay_ms: int) -> QTimer:
        """Create and start a single-shot QTimer for the retry callback."""
        timer = QTimer(self._parent)
        timer.setSingleShot(True)
        timer.timeout.connect(callback)
        timer.start(int(delay_ms))
        return timer

    @staticmethod
    def _stop_timer(handle: SchedulerHandle) -> None:
        """Stop and dispose of the scheduled timer handle."""
        try:
            if handle is not None:
                handle.stop()
                handle.deleteLater()
        except Exception:  # pragma: no cover - defensive guard
            logger.debug("Failed to cancel timer handle", exc_info=True)


@dataclass(frozen=True)
class RetryCategorySnapshot(Generic[K, P]):
    """Per-category counters exposed via :meth:`RetryController.snapshot`."""

    active: int
    total_scheduled: int
    peak_active: int | None = None


@dataclass(frozen=True)
class RetrySnapshot(Generic[K, P]):
    """Structured snapshot used by diagnostics providers."""

    categories: dict[str, RetryCategorySnapshot[K, P]]


def qt_retry_dispatcher(
    executor: object, *, category: str
) -> Callable[[Callable[[], None]], None] | None:
    """Return an executor-backed dispatcher for retry timers when available.

    Args:
        executor: Executor that may expose ``dispatch_to_main_thread``.
        category: Category used when dispatching to the main thread.

    Returns:
        Callable that enqueues callbacks on the Qt main thread, or ``None`` when
        dispatch is unsupported.
    """
    if executor is None:
        return None
    dispatcher = getattr(executor, "dispatch_to_main_thread", None)
    if not callable(dispatcher):
        return None

    def _dispatch(callback: Callable[[], None]) -> None:
        """Enqueue ``callback`` onto the Qt main thread with the given category."""
        dispatcher(callback, category=category)

    return _dispatch


@dataclass
class _Entry(Generic[K, P]):
    """Internal representation of a pending retry request."""

    attempts: int
    payload: P
    handle: SchedulerHandle | None
    submit: Callable[[P, int], TaskHandle]
    coalesce: Callable[[P, P], P] | None
    throttle: Callable[[K, int, TaskRejected], None]
    started_at: float
    on_give_up: Callable[[K, P, int], None] | None


class RetryController(Generic[K, P]):
    """Generic retry manager that encapsulates exponential backoff policies."""

    def __init__(
        self,
        category: str,
        policy: BackoffPolicy | RetryPolicy[K, P],
        *,
        scheduler: Scheduler,
        contextProvider: Callable[[K, P], RetryContext[K, P]] | None = None,
    ) -> None:
        """Initialise the retry controller with policy and scheduling hooks.

        Args:
            category: Diagnostics label used when reporting this controller.
            policy: Backoff or retry policy controlling delays and termination.
            scheduler: Scheduler responsible for waiting between attempts.
            contextProvider: Optional callable returning ``RetryContext`` values.
        """
        self._category = category
        self._policy = policy if isinstance(policy, RetryPolicy) else RetryPolicy(policy)  # type: ignore[arg-type]
        self._scheduler = scheduler
        self._contextProvider = contextProvider
        self._entries: dict[K, _Entry[K, P]] = {}
        self.totalScheduled: int = 0  # diagnostics counter
        self.peakActive: int = 0

    def queueOrCoalesce(
        self,
        key: K,
        payload: P,
        *,
        submit: Callable[[P, int], TaskHandle],
        coalesce: Callable[[P, P], P] | None = None,
        throttle: Callable[[K, int, TaskRejected], None],
        onGiveUp: Callable[[K, P, int], None] | None = None,
    ) -> None:
        """Submit work or coalesce with an existing retry entry.

        Args:
            key: Identifier used to deduplicate retries.
            payload: Value passed to ``submit`` or stored for the next attempt.
            submit: Callable that enqueues the work and returns a ``TaskHandle``.
            coalesce: Optional merger invoked when the key already exists.
            throttle: Callback invoked whenever ``submit`` raises ``TaskRejected``.
            onGiveUp: Optional hook fired when the termination policy ends retries.
        """
        entry = self._entries.get(key)
        if entry is not None:
            merger = coalesce or entry.coalesce
            entry.payload = merger(entry.payload, payload) if merger else payload
            if coalesce is not None:
                entry.coalesce = coalesce
            if onGiveUp is not None:
                entry.on_give_up = onGiveUp
            return
        # No pending retry: attempt initial submit
        self._attempt_submit(
            key,
            payload,
            attempt=0,
            submit=submit,
            throttle=throttle,
            coalesce=coalesce,
            on_give_up=onGiveUp,
            started_at=None,
        )

    def onSuccess(self, key: K) -> None:
        """Clear retry bookkeeping for ``key`` after a successful completion."""
        self.cancel(key)

    def onFailure(self, key: K) -> None:
        """Clear retry bookkeeping on hard failure (non-retryable)."""
        self.cancel(key)

    def cancel(self, key: K) -> None:
        """Cancel any scheduled retry for ``key`` and forget its entry."""
        entry = self._entries.pop(key, None)
        if entry and entry.handle is not None:
            self._scheduler.cancel(entry.handle)

    def cancelAll(self) -> None:
        """Cancel and drop every queued retry entry."""
        for k in list(self._entries.keys()):
            self.cancel(k)

    def pendingKeys(self) -> Iterable[K]:
        """Return the keys currently waiting to be retried."""
        return list(self._entries.keys())

    def snapshot(self) -> RetrySnapshot[K, P]:
        """Return a structured diagnostics snapshot for overlays and tests.

        Returns:
            RetrySnapshot containing counts for this controller's category.
        """
        info = RetryCategorySnapshot(
            active=len(self._entries),
            total_scheduled=self.totalScheduled,
            peak_active=self.peakActive,
        )
        return RetrySnapshot(categories={self._category: info})

    def _make_context(self, key: K, payload: P) -> RetryContext[K, P]:
        """Build a :class:`RetryContext` for ``key`` and ``payload``."""
        provider = getattr(self, "_contextProvider", None)
        if provider is not None:
            try:
                ctx = provider(key, payload)  # type: ignore[misc]
                if isinstance(ctx, RetryContext):
                    return ctx
            except Exception:
                logger.debug("contextProvider raised", exc_info=True)
        size: int | None = None
        try:
            if hasattr(payload, "sizeInBytes"):
                size = int(payload.sizeInBytes())  # type: ignore[call-arg]
            elif isinstance(payload, (bytes, bytearray)):
                size = len(payload)  # type: ignore[arg-type]
        except Exception:
            logger.debug("Retry payload size inspection failed", exc_info=True)
            size = None
        return RetryContext(
            category=self._category, device=None, key=key, payload_size=size
        )

    def _attempt_submit(
        self,
        key: K,
        payload: P,
        *,
        attempt: int,
        submit: Callable[[P, int], TaskHandle],
        throttle: Callable[[K, int, TaskRejected], None],
        coalesce: Callable[[P, P], P] | None,
        on_give_up: Callable[[K, P, int], None] | None,
        started_at: float | None,
    ) -> None:
        """Attempt immediate submission and fall back to scheduling retries."""
        try:
            submit(payload, attempt)
        except TaskRejected as exc:
            next_attempt = max(1, attempt + 1)
            try:
                throttle(key, next_attempt, exc)
            except Exception:  # pragma: no cover - defensive guard
                logger.debug("Throttle callback raised", exc_info=True)
            ctx = self._make_context(key, payload)
            start = started_at if started_at is not None else monotonic()
            if self._policy.shouldGiveUp(
                next_attempt, started_at=start, now=monotonic(), context=ctx
            ):
                if on_give_up is not None:
                    try:
                        on_give_up(key, payload, next_attempt)
                    except Exception:
                        logger.debug("onGiveUp callback raised", exc_info=True)
                return
            self._schedule_retry(
                key,
                payload,
                attempts=next_attempt,
                submit=submit,
                throttle=throttle,
                coalesce=coalesce,
                on_give_up=on_give_up,
                started_at=start,
            )

    def _schedule_retry(
        self,
        key: K,
        payload: P,
        *,
        attempts: int,
        submit: Callable[[P, int], TaskHandle],
        throttle: Callable[[K, int, TaskRejected], None],
        coalesce: Callable[[P, P], P] | None,
        on_give_up: Callable[[K, P, int], None] | None,
        started_at: float,
    ) -> None:
        """Schedule the retry according to the policy and scheduler."""

        def _on_timeout() -> None:
            """Run the retry submission once the backoff delay elapses."""
            # Pop, then re-attempt submission with current payload
            entry = self._entries.pop(key, None)
            if entry is None:
                return
            self._attempt_submit(
                key,
                entry.payload,
                attempt=entry.attempts,
                submit=entry.submit,
                throttle=entry.throttle,
                coalesce=entry.coalesce,
                on_give_up=entry.on_give_up,
                started_at=entry.started_at,
            )

        ctx = self._make_context(key, payload)
        delay_ms = self._policy.nextDelayMs(attempts, ctx)
        try:
            handle = self._scheduler.schedule(key, delay_ms, _on_timeout)
        except RetrySchedulingError:
            logger.error(
                "Retry scheduling failed for %s (attempt=%s); giving up", key, attempts
            )
            if on_give_up is not None:
                try:
                    on_give_up(key, payload, attempts)
                except Exception:
                    logger.debug("onGiveUp callback raised", exc_info=True)
            return
        if handle is None:
            logger.error(
                "Retry scheduling failed for %s (attempt=%s); scheduler returned None",
                key,
                attempts,
            )
            if on_give_up is not None:
                try:
                    on_give_up(key, payload, attempts)
                except Exception:
                    logger.debug("onGiveUp callback raised", exc_info=True)
            return
        if isinstance(handle, _ProxyTimerHandle) and handle.cancelled:
            logger.error(
                "Retry scheduling failed for %s (attempt=%s); dispatcher or timer creation failed",
                key,
                attempts,
            )
            try:
                handle.deleteLater()
            except Exception:
                logger.debug(
                    "deleteLater raised on cancelled proxy handle", exc_info=True
                )
            if on_give_up is not None:
                try:
                    on_give_up(key, payload, attempts)
                except Exception:
                    logger.debug("onGiveUp callback raised", exc_info=True)
            return
        self.totalScheduled += 1
        self._entries[key] = _Entry(
            attempts=attempts,
            payload=payload,
            handle=handle,
            submit=submit,
            coalesce=coalesce,
            throttle=throttle,
            started_at=started_at,
            on_give_up=on_give_up,
        )
        # update peak after entry creation to reflect current set size
        size = len(self._entries)
        self.peakActive = max(self.peakActive, size)


def makeQtRetryController(
    category: str,
    base_ms: int,
    max_ms: int,
    *,
    parent: QObject,
    jitter_pct: float = 0.25,
    contextProvider: Callable[[K, P], RetryContext[K, P]] | None = None,
    dispatcher: Callable[[Callable[[], None]], None] | None = None,
) -> RetryController[K, P]:
    """Factory for a Qt-backed RetryController with standard backoff.

    Args:
        category: Diagnostics label used for the retry snapshot.
        base_ms: Initial retry delay in milliseconds.
        max_ms: Maximum retry delay in milliseconds.
        parent: QObject parent that will own the underlying timers.
        jitter_pct: Fraction of each delay allocated to random jitter.
        contextProvider: Optional callable returning ``RetryContext`` instances.
        dispatcher: Optional callable that enqueues callbacks on the Qt main thread to keep timer creation thread-safe.

    Returns:
        Configured ``RetryController`` ready to queue retries on Qt timers with main-thread enforcement.
    """
    policy = BackoffPolicy(base_ms, max_ms, jitter_pct)
    return RetryController(
        category,
        policy,
        scheduler=QtTimerScheduler(parent, dispatcher=dispatcher),
        contextProvider=contextProvider,
    )
