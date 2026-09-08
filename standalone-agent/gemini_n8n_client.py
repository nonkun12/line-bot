"""Synchronous client for the n8n Gemini Agent webhook.

This module is intentionally isolated from the existing Groq/LangGraph path.
It does not change the default provider; callers must explicitly invoke it.
"""

from __future__ import annotations

import os

import httpx


class GeminiN8nError(RuntimeError):
    """Raised when the n8n Gemini endpoint cannot return a usable reply."""


def call_gemini_via_n8n(
    message: str,
    user_id: str,
    request_id: str,
    *,
    timeout: float = 10.0,
) -> dict:
    """Call the internal n8n Gemini webhook and return its JSON response.

    Required environment variables:
      GEMINI_N8N_WEBHOOK_URL
      GEMINI_N8N_INTERNAL_KEY

    The function deliberately does not retry: a generated response should not
    be duplicated by an automatic second request. The caller can fall back to
    the existing Groq path on GeminiN8nError.
    """
    webhook_url = os.getenv("GEMINI_N8N_WEBHOOK_URL", "").strip()
    internal_key = os.getenv("GEMINI_N8N_INTERNAL_KEY", "").strip()

    if not webhook_url:
        raise GeminiN8nError("GEMINI_N8N_WEBHOOK_URL is not configured")
    if not internal_key:
        raise GeminiN8nError("GEMINI_N8N_INTERNAL_KEY is not configured")

    payload = {
        "request_id": request_id,
        "user_id": user_id,
        "message": message,
    }
    headers = {
        "Content-Type": "application/json",
        "X-Internal-Key": internal_key,
    }

    try:
        response = httpx.post(
            webhook_url,
            json=payload,
            headers=headers,
            timeout=timeout,
        )
    except httpx.TimeoutException as exc:
        raise GeminiN8nError("Gemini n8n webhook timeout") from exc
    except httpx.HTTPError as exc:
        raise GeminiN8nError(f"Gemini n8n request failed: {exc}") from exc

    if response.status_code != 200:
        raise GeminiN8nError(
            f"Gemini n8n returned HTTP {response.status_code}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise GeminiN8nError("Gemini n8n returned invalid JSON") from exc

    reply = data.get("reply")
    if not isinstance(reply, str) or not reply.strip():
        raise GeminiN8nError("Gemini n8n returned empty reply")

    return data
