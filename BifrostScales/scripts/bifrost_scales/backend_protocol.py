"""Backend protocol for preview implementations."""

from __future__ import annotations

from typing import Any, Protocol

from .scheduler import PreviewRequest


class PreviewBackend(Protocol):
    """Minimal boundary used by the scheduler.

    The production implementation targets the immutable Native Bifrost graph.
    The protocol keeps the scheduler independent from Maya scene-authoring details.
    """

    def apply(self, request: PreviewRequest) -> Any:
        """Apply one immutable preview request and return a host report."""
