"""Optional boundary for external workflow automation such as n8n.

The AI Core does not depend on n8n. A caller may provide an external workflow
handler for integrations that benefit from visual orchestration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .gateway import AIRequest, AIResponse


@dataclass(frozen=True)
class WorkflowResult:
    handled: bool
    response: AIResponse | None = None


class ExternalWorkflow:
    """Vendor-neutral adapter for optional workflow automation."""

    def __init__(self, handler: Callable[[AIRequest], AIResponse | str]):
        if not callable(handler):
            raise TypeError("handler must be callable")
        self._handler = handler

    def handle(self, request: AIRequest) -> WorkflowResult:
        if not isinstance(request, AIRequest):
            raise TypeError("request must be an AIRequest")
        result = self._handler(request)
        if isinstance(result, AIResponse):
            return WorkflowResult(handled=True, response=result)
        if isinstance(result, str):
            return WorkflowResult(handled=True, response=AIResponse(text=result))
        raise TypeError("handler must return AIResponse or str")
