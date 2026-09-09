"""Small channel-independent gateway contract.

Channels should translate their native input into AIRequest and consume AIResponse.
Business logic stays outside LINE/Web/Voice adapters.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class AIRequest:
    user_id: str
    message: str
    channel: str = "unknown"
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AIResponse:
    text: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


class AIGateway:
    """Adapter boundary for future LINE, Web, iPhone and voice channels."""

    def __init__(self, handler: Callable[[AIRequest], AIResponse | str]):
        self._handler = handler

    def handle(self, request: AIRequest) -> AIResponse:
        if not isinstance(request, AIRequest):
            raise TypeError("request must be an AIRequest")
        if not isinstance(request.user_id, str) or not request.user_id.strip():
            raise ValueError("user_id is required")
        if not isinstance(request.message, str) or not request.message.strip():
            raise ValueError("message is required")
        if not isinstance(request.channel, str) or not request.channel.strip():
            raise ValueError("channel is required")

        result = self._handler(request)
        if isinstance(result, AIResponse):
            return result
        if isinstance(result, str):
            return AIResponse(text=result)
        raise TypeError("handler must return AIResponse or str")
