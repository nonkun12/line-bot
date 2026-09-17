"""Restricted text-only AI boundary for advisory/self-improvement agents.

This module intentionally has no access to application config or tool definitions.
It creates only plain assistant text and is suitable for read-only Agent execution.
"""
from __future__ import annotations

import os

from groq import Groq

DEFAULT_ADVISORY_MODEL = "openai/gpt-oss-20b"


def generate_advisory_text(
    *,
    messages: list[dict[str, str]],
    temperature: float = 0.2,
    max_tokens: int = 1200,
    client: Groq | None = None,
    model: str | None = None,
) -> str:
    """Return assistant text without exposing tool/function-call parameters."""
    if not messages:
        raise ValueError("messages are required")
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if client is None and not api_key:
        raise RuntimeError("GROQ_API_KEY is required for advisory AI execution")
    active_client = client or Groq(api_key=api_key, timeout=15.0, max_retries=1)
    active_model = (model or os.environ.get("ADVISORY_MODEL") or DEFAULT_ADVISORY_MODEL).strip()
    if not active_model:
        raise ValueError("model is required")
    response = active_client.chat.completions.create(
        model=active_model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    choices = getattr(response, "choices", None) or []
    if not choices:
        raise RuntimeError("Groq returned no choices")
    message = getattr(choices[0], "message", None)
    text = getattr(message, "content", None)
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("Groq returned empty content")
    return text.strip()


__all__ = ["DEFAULT_ADVISORY_MODEL", "generate_advisory_text"]
