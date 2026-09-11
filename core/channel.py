"""Channel-to-Core request adaptation helpers."""

from __future__ import annotations

import os
from typing import Any, Mapping

from .gateway import AIGateway, AIRequest, AIResponse
from app_development import extract_app_development_request, dispatch_app_development_workflow


def handle_channel_request(
    gateway: AIGateway,
    user_id: str,
    message: str,
    channel: str,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> AIResponse:
    """Translate channel-native values into one shared AI Gateway request."""
    if channel.strip().lower() == "line":
        requirement = extract_app_development_request(message)
        if requirement is not None:
            reply = dispatch_app_development_workflow(
                requirement,
                user_id=str(user_id),
                token=os.environ.get("GITHUB_TOKEN", ""),
            )
            return AIResponse(text=reply, metadata={"route": "app-development"})

    request = AIRequest(
        user_id=user_id,
        message=message,
        channel=channel,
        metadata=dict(metadata or {}),
    )
    return gateway.handle(request)
