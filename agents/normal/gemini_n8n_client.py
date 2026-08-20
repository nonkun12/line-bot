"""
Gemini 2.5 Flash via n8n client.

This module is intentionally isolated from the existing Normal Agent.
It provides the first implementation step for the Gemini migration without
changing the current Groq path or LINE request routing.

Environment variables:
    GEMINI_N8N_WEBHOOK_URL: n8n webhook used for synchronous Gemini requests.
    GEMINI_N8N_TIMEOUT: request timeout in seconds (default: 10).
    GEMINI_N8N_INTERNAL_KEY: optional shared secret sent as x-internal-key.

Expected request JSON:
    {"message": "...", "user_id": "..."}

Accepted response shapes:
    {"reply": "..."}
    {"text": "..."}
    {"output": "..."}
"""

import os

import httpx


DEFAULT_TIMEOUT = 10.0


class GeminiN8nError(RuntimeError):
    """Raised when the n8n Gemini endpoint cannot return a usable reply."""


def _timeout() -> float:
    raw = os.getenv("GEMINI_N8N_TIMEOUT", str(DEFAULT_TIMEOUT))
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = DEFAULT_TIMEOUT
    return max(1.0, min(value, 30.0))


def call_gemini_via_n8n(message: str, user_id: str) -> str:
    """Synchronously request a Gemini response from the n8n workflow.

    No retry is performed here. A caller can safely catch GeminiN8nError and
    fall back to the existing Groq implementation without duplicating a
    potentially side-effecting request.
    """
    url = (os.getenv("GEMINI_N8N_WEBHOOK_URL") or "").strip()
    if not url:
        raise GeminiN8nError("GEMINI_N8N_WEBHOOK_URL is not configured")

    headers = {"Content-Type": "application/json"}
    internal_key = (os.getenv("GEMINI_N8N_INTERNAL_KEY") or "").strip()
    if internal_key:
        headers["x-internal-key"] = internal_key

    payload = {
        "message": message,
        "user_id": user_id,
    }

    try:
        response = httpx.post(
            url,
            json=payload,
            headers=headers,
            timeout=_timeout(),
        )
        response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise GeminiN8nError("n8n Gemini request timed out") from exc
    except httpx.HTTPError as exc:
        raise GeminiN8nError(f"n8n Gemini request failed: {exc}") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise GeminiN8nError("n8n Gemini endpoint returned non-JSON") from exc

    if not isinstance(data, dict):
        raise GeminiN8nError("n8n Gemini endpoint returned an invalid response")

    reply = data.get("reply") or data.get("text") or data.get("output")
    if not isinstance(reply, str) or not reply.strip():
        raise GeminiN8nError("n8n Gemini endpoint returned no reply")

    return reply.strip()
