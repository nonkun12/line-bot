"""Explicit loopback-only adapter for a local Ollama OpenAI-compatible server.

No cloud endpoint, API key, provider fallback, subprocess, or automatic model
selection is used. The caller must opt in and supply the local model name.
"""
from __future__ import annotations

import ipaddress
import json
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class LocalModelUnavailable(RuntimeError):
    """The configured local model endpoint could not provide a valid response."""


class OllamaLocalModelCall:
    """Call a local Ollama /v1/chat/completions endpoint with bounded I/O."""

    def __init__(
        self,
        *,
        model: str,
        base_url: str = "http://127.0.0.1:11434/v1",
        timeout_seconds: float = 20.0,
        max_response_bytes: int = 65536,
    ) -> None:
        if not isinstance(model, str) or not model.strip() or len(model) > 160:
            raise ValueError("a bounded local model name is required")
        if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool) or not 1 <= timeout_seconds <= 60:
            raise ValueError("timeout_seconds must be between 1 and 60")
        if not isinstance(max_response_bytes, int) or isinstance(max_response_bytes, bool) or not 1024 <= max_response_bytes <= 262144:
            raise ValueError("max_response_bytes must be between 1024 and 262144")

        parsed = urlsplit(str(base_url))
        if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("local model endpoint must be an unauthenticated HTTP loopback URL")
        if parsed.query or parsed.fragment:
            raise ValueError("local model endpoint must not contain query or fragment")
        host = parsed.hostname.casefold()
        is_loopback = host == "localhost"
        if not is_loopback:
            try:
                is_loopback = ipaddress.ip_address(host).is_loopback
            except ValueError:
                is_loopback = False
        if not is_loopback:
            raise ValueError("remote model endpoints are forbidden; use localhost only")
        self._endpoint = base_url.rstrip("/") + "/chat/completions"
        self._model = model.strip()
        self._timeout = float(timeout_seconds)
        self._max_response_bytes = max_response_bytes

    def __call__(self, prompt: str) -> str:
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 12000:
            raise ValueError("prompt must contain 1 to 12000 characters")
        body = json.dumps(
            {
                "model": self._model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 400,
                "stream": False,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = Request(
            self._endpoint,
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self._timeout) as response:
            raw = response.read(self._max_response_bytes + 1)
        if len(raw) > self._max_response_bytes:
            raise LocalModelUnavailable("local model response exceeded size limit")
        try:
            payload = json.loads(raw.decode("utf-8"))
            content = payload["choices"][0]["message"]["content"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise LocalModelUnavailable("local model returned an invalid chat response") from exc
        if not isinstance(content, str) or not content.strip() or len(content) > 12000:
            raise LocalModelUnavailable("local model returned empty or oversized content")
        return content.strip()


__all__ = ["LocalModelUnavailable", "OllamaLocalModelCall"]
