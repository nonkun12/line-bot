"""Channel-to-Core request adaptation helpers."""

from __future__ import annotations

from typing import Any, Mapping

from .gateway import AIGateway, AIRequest, AIResponse


def handle_channel_request(
    gateway: AIGateway,
    user_id: str,
    message: str,
    channel: str,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> AIResponse:
    """Translate channel-native values into one shared AI Gateway request."""
    request = AIRequest(
        user_id=user_id,
        message=message,
        channel=channel,
        metadata=dict(metadata or {}),
    )
    return gateway.handle(request)
