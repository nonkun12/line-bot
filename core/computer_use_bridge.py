"""Fail-closed placeholder for a future Mac-local Computer Use adapter.

No trusted local approval UI or desktop adapter is connected yet. Therefore this
module intentionally cannot execute desktop actions, even when a caller passes
an adapter or sets enabled=True. A confirmation string is not proof of a human
interaction and must never be treated as authorization.
"""
from __future__ import annotations

from typing import Any, Protocol

from core.desktop_control import DesktopPlan, DesktopExecutionDisabled


class ApprovalError(RuntimeError):
    """A requested approval cannot be established by a trusted local UI."""


class ComputerUseAdapter(Protocol):
    """Future narrow adapter contract; implementations must not expose shell access."""

    def snapshot(self) -> Any:
        """Return a bounded screenshot/accessibility snapshot without changing state."""

    def act(self, app: str, operation: str, params: dict[str, Any]) -> Any:
        """Execute exactly one validated operation in the foreground application."""


def approve_plan(*args: Any, **kwargs: Any) -> None:
    """Approval is unavailable until a trusted local approval UI is integrated."""
    raise ApprovalError("trusted_local_approval_ui_not_connected")


class LocalComputerUseBridge:
    """Execution remains disabled until a separately reviewed trusted UI exists."""

    def __init__(self, adapter: ComputerUseAdapter | None = None, *, enabled: bool = False):
        # Keep constructor compatibility, but never store or invoke the adapter.
        # enabled=True is not authorization.
        self._disabled_reason = "trusted_local_approval_ui_not_connected"

    def snapshot(self) -> Any:
        raise DesktopExecutionDisabled(self._disabled_reason)

    def execute(
        self,
        plan: DesktopPlan,
        grant: Any = None,
        *,
        now: float | None = None,
    ) -> list[Any]:
        raise DesktopExecutionDisabled(self._disabled_reason)


__all__ = [
    "ApprovalError", "ComputerUseAdapter", "LocalComputerUseBridge", "approve_plan",
]
