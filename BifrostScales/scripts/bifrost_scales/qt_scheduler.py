"""Qt host wrapper around the dependency-free latest-wins scheduler."""

from __future__ import annotations

import time
from typing import Any, Mapping

from .backend_protocol import PreviewBackend
from .qt_compat import QtCore
from .scheduler import ChangeCategory, PreviewSchedulerCore


class QtPreviewScheduler(QtCore.QObject):
    status_changed = QtCore.Signal(str)
    request_started = QtCore.Signal(int, str)
    request_finished = QtCore.Signal(int, str, object)
    request_failed = QtCore.Signal(int, str)

    def __init__(
        self,
        backend: PreviewBackend,
        interactive_delay_ms: int = 60,
        settled_delay_ms: int = 180,
        parent: Any | None = None,
    ) -> None:
        super().__init__(parent)
        self.backend = backend
        self.core = PreviewSchedulerCore(
            interactive_delay_ms=interactive_delay_ms,
            settled_delay_ms=settled_delay_ms,
        )
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._flush_due)

    def configure_delays(self, interactive_ms: int, settled_ms: int) -> None:
        self.core.configure_delays(interactive_ms, settled_ms)
        self._arm()

    def begin_interaction(self) -> None:
        self.core.begin_interaction()
        self.status_changed.emit("Interactive")
        self._arm()

    def end_interaction(self) -> None:
        self.core.end_interaction()
        self.status_changed.emit("Refining")
        self._arm()

    def queue_change(self, category: ChangeCategory, values: Mapping[str, Any]) -> int:
        revision = self.core.queue_change(category, values)
        self._arm()
        return revision

    def request_settled(
        self,
        category: ChangeCategory,
        values: Mapping[str, Any],
        immediate: bool = False,
    ) -> int:
        revision = self.core.request_settled(category, values, immediate=immediate)
        self.status_changed.emit("Refining")
        self._arm()
        return revision

    def pause(self) -> None:
        self._timer.stop()
        self.core.pause()
        self.status_changed.emit("Paused")

    def resume(self) -> None:
        self.core.resume()
        self.status_changed.emit("Idle")
        self._arm()

    def clear_error(self) -> None:
        self._timer.stop()
        self.core.clear_error()
        self.status_changed.emit("Idle")

    def _arm(self) -> None:
        delay = self.core.next_due_in_ms()
        if delay is not None:
            self._timer.start(max(0, delay))

    @QtCore.Slot()
    def _flush_due(self) -> None:
        request = self.core.poll()
        if request is None:
            self._arm()
            return
        self.request_started.emit(request.revision, request.mode.value)
        self.status_changed.emit(
            "Interactive" if request.mode.value == "interactive" else "Refining"
        )
        started = time.monotonic()
        try:
            report = self.backend.apply(request)
        except Exception as exc:
            message = "{}: {}".format(type(exc).__name__, exc)
            self.core.complete(request.revision, False, message)
            self.status_changed.emit("Error")
            self.request_failed.emit(request.revision, message)
            return
        elapsed_ms = (time.monotonic() - started) * 1000.0
        self.core.complete(request.revision, True)
        self.status_changed.emit("Up to date ({:.1f} ms)".format(elapsed_ms))
        self.request_finished.emit(request.revision, request.mode.value, report)
        self._arm()
