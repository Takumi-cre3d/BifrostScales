"""Dependency-free latest-wins preview scheduler core."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Any, Callable, Mapping


class ChangeCategory(IntEnum):
    DISPLAY = 0
    APPEARANCE = 1
    SHAPE = 2
    CELL = 3
    ORIENTATION = 4
    DISTRIBUTION = 5


class PreviewMode(str, Enum):
    INTERACTIVE = "interactive"
    SETTLED = "settled"


class SchedulerState(str, Enum):
    IDLE = "idle"
    ARMED = "armed"
    EVALUATING = "evaluating"
    PAUSED = "paused"
    ERROR = "error"


@dataclass(frozen=True)
class PreviewRequest:
    revision: int
    mode: PreviewMode
    categories: frozenset[ChangeCategory]
    scope: ChangeCategory
    snapshot: Mapping[str, Any]
    created_at: float


@dataclass(frozen=True)
class SchedulerStatus:
    state: SchedulerState
    revision: int
    applied_revision: int
    inflight_revision: int | None
    pending: bool
    dragging: bool
    error: str


class PreviewSchedulerCore:
    """Coalesces UI events and keeps only the newest pending state.

    The core never owns threads. A host wrapper calls :meth:`poll` when the
    next deadline is reached, evaluates one request, then calls
    :meth:`complete`. Changes arriving while a request is evaluating are
    merged into a single newest request instead of forming a FIFO backlog.
    """

    def __init__(
        self,
        interactive_delay_ms: int = 60,
        settled_delay_ms: int = 180,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.interactive_delay = max(0, int(interactive_delay_ms)) / 1000.0
        self.settled_delay = max(0, int(settled_delay_ms)) / 1000.0
        self._clock = clock or time.monotonic
        self._snapshot: dict[str, Any] = {}
        self._pending_categories: set[ChangeCategory] = set()
        self._interaction_categories: set[ChangeCategory] = set()
        self._revision = 0
        self._applied_revision = 0
        self._inflight: PreviewRequest | None = None
        self._due_at: float | None = None
        self._dragging = False
        self._paused = False
        self._error = ""

    @property
    def status(self) -> SchedulerStatus:
        if self._error:
            state = SchedulerState.ERROR
        elif self._paused:
            state = SchedulerState.PAUSED
        elif self._inflight is not None:
            state = SchedulerState.EVALUATING
        elif self._pending_categories:
            state = SchedulerState.ARMED
        else:
            state = SchedulerState.IDLE
        return SchedulerStatus(
            state=state,
            revision=self._revision,
            applied_revision=self._applied_revision,
            inflight_revision=(
                self._inflight.revision if self._inflight is not None else None
            ),
            pending=bool(self._pending_categories),
            dragging=self._dragging,
            error=self._error,
        )

    @property
    def snapshot(self) -> dict[str, Any]:
        return dict(self._snapshot)

    def configure_delays(
        self, interactive_delay_ms: int, settled_delay_ms: int
    ) -> None:
        self.interactive_delay = max(0, int(interactive_delay_ms)) / 1000.0
        self.settled_delay = max(0, int(settled_delay_ms)) / 1000.0

    def begin_interaction(self, now: float | None = None) -> None:
        if self._paused or self._error:
            return
        self._dragging = True
        current = self._now(now)
        if self._pending_categories:
            self._due_at = current + self.interactive_delay

    def end_interaction(self, now: float | None = None) -> None:
        was_dragging = self._dragging
        if self._paused or self._error:
            self._dragging = False
            return
        self._dragging = False
        if not was_dragging:
            return
        if not self._interaction_categories and not self._pending_categories:
            return
        categories = self._interaction_categories or self._pending_categories
        self._pending_categories.update(categories)
        self._revision += 1
        self._due_at = self._now(now) + self.settled_delay
        self._interaction_categories.clear()

    def queue_change(
        self,
        category: ChangeCategory,
        values: Mapping[str, Any] | None = None,
        now: float | None = None,
    ) -> int:
        if self._paused or self._error:
            return self._revision
        normalized = ChangeCategory(category)
        if values:
            self._snapshot.update(dict(values))
        self._revision += 1
        self._pending_categories.add(normalized)
        if self._dragging:
            self._interaction_categories.add(normalized)
        delay = self.interactive_delay if self._dragging else self.settled_delay
        self._due_at = self._now(now) + delay
        return self._revision

    def request_settled(
        self,
        category: ChangeCategory = ChangeCategory.DISTRIBUTION,
        values: Mapping[str, Any] | None = None,
        now: float | None = None,
        immediate: bool = False,
    ) -> int:
        if self._paused or self._error:
            return self._revision
        if values:
            self._snapshot.update(dict(values))
        normalized = ChangeCategory(category)
        self._revision += 1
        self._pending_categories.add(normalized)
        self._dragging = False
        self._interaction_categories.clear()
        self._due_at = self._now(now) + (0.0 if immediate else self.settled_delay)
        return self._revision

    def next_due_in_ms(self, now: float | None = None) -> int | None:
        if (
            self._paused
            or self._error
            or self._inflight is not None
            or not self._pending_categories
            or self._due_at is None
        ):
            return None
        remaining = max(0.0, self._due_at - self._now(now))
        return int(round(remaining * 1000.0))

    def poll(self, now: float | None = None) -> PreviewRequest | None:
        if (
            self._paused
            or self._error
            or self._inflight is not None
            or not self._pending_categories
            or self._due_at is None
        ):
            return None
        current = self._now(now)
        if current + 1.0e-12 < self._due_at:
            return None
        categories = frozenset(self._pending_categories)
        request = PreviewRequest(
            revision=self._revision,
            mode=(
                PreviewMode.INTERACTIVE
                if self._dragging
                else PreviewMode.SETTLED
            ),
            categories=categories,
            scope=max(categories),
            snapshot=dict(self._snapshot),
            created_at=current,
        )
        self._pending_categories.clear()
        self._due_at = None
        self._inflight = request
        return request

    def complete(
        self,
        revision: int,
        success: bool,
        error: str = "",
        now: float | None = None,
    ) -> bool:
        if self._inflight is None or int(revision) != self._inflight.revision:
            return False
        completed = self._inflight
        self._inflight = None
        if not success:
            self._error = str(error or "Preview evaluation failed")
            self._pending_categories.clear()
            self._interaction_categories.clear()
            self._due_at = None
            self._dragging = False
            return True
        self._applied_revision = max(self._applied_revision, completed.revision)
        if self._pending_categories and self._due_at is None:
            delay = self.interactive_delay if self._dragging else self.settled_delay
            self._due_at = self._now(now) + delay
        return True

    def pause(self) -> None:
        self._paused = True
        self._pending_categories.clear()
        self._interaction_categories.clear()
        self._due_at = None
        self._dragging = False

    def resume(self) -> None:
        if self._error:
            return
        self._paused = False

    def clear_error(self) -> None:
        self._error = ""
        self._paused = False
        self._inflight = None
        self._pending_categories.clear()
        self._interaction_categories.clear()
        self._due_at = None
        self._dragging = False

    def _now(self, supplied: float | None) -> float:
        return self._clock() if supplied is None else float(supplied)
