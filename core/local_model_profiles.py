"""Explicit, loopback-only profiles for local Creator/Critic models.

Bonsai and LFM are configured independently. No endpoint or model identifier
is guessed; callers must provide both values for the selected profile.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


class _RejectRedirects(HTTPRedirectHandler):
    """Do not allow a local endpoint to redirect prompts to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class LocalModelProfile:
    name: str
    base_url: str
    model: str
    api_key: str = ""
    timeout: float = 30.0


def _validate_loopback_url(base_url: str) -> str:
    endpoint = base_url.strip().rstrip("/")
    parsed = urlparse(endpoint)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("local model endpoint must be an HTTP loopback URL without credentials, query, or fragment")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("local model endpoint has an invalid port") from exc
    return endpoint


def load_local_model_profile(provider: str, environ=None) -> LocalModelProfile:
    """Load a named profile from environment; never infer a model or port."""
    values = os.environ if environ is None else environ
    name = provider.strip().lower()
    if name not in {"bonsai", "lfm"}:
        raise ValueError("provider must be 'bonsai' or 'lfm'")
    prefix = f"CREATOR_CRITIC_{name.upper()}"
    raw_url = values.get(f"{prefix}_BASE_URL", "")
    model = values.get(f"{prefix}_MODEL", "").strip()
    if not raw_url.strip() or not model:
        raise RuntimeError(f"{prefix}_BASE_URL and {prefix}_MODEL are required")
    timeout_raw = values.get(f"{prefix}_TIMEOUT", "30")
    try:
        timeout = float(timeout_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{prefix}_TIMEOUT must be a number") from exc
    if not 1 <= timeout <= 120:
        raise ValueError(f"{prefix}_TIMEOUT must be between 1 and 120 seconds")
    return LocalModelProfile(
        name=name,
        base_url=_validate_loopback_url(raw_url),
        model=model,
        api_key=values.get(f"{prefix}_API_KEY", "").strip(),
        timeout=timeout,
    )


def local_model_call(prompt: str, profile: LocalModelProfile) -> str:
    """Send one chat completion to a validated local model profile."""
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt is required")
    body = json.dumps({
        "model": profile.model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if profile.api_key:
        headers["Authorization"] = f"Bearer {profile.api_key}"
    request = Request(
        f"{profile.base_url}/chat/completions",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        opener = build_opener(_RejectRedirects)
        with opener.open(request, timeout=profile.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{profile.name} local model request failed: {type(exc).__name__}") from None
    choices = payload.get("choices") if isinstance(payload, dict) else None
    message = choices[0].get("message") if isinstance(choices, list) and choices and isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError(f"{profile.name} local model returned empty content")
    return content.strip()


__all__ = [
    "LocalModelProfile",
    "load_local_model_profile",
    "local_model_call",
]
