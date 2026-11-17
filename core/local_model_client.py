"""Fail-closed local-only chat client with a Groq-compatible call surface.

Only explicit loopback HTTP endpoints are accepted. Redirects, credentials,
remote hosts, retries, and cloud fallbacks are disabled.
"""
from __future__ import annotations

import json
import os
import socket
from types import SimpleNamespace
from urllib import error, request
from urllib.parse import urlsplit


class LocalModelError(RuntimeError):
    pass


def _is_loopback(hostname: str) -> bool:
    if not hostname:
        return False
    if hostname.casefold() == "localhost":
        return True
    try:
        return ip_address(hostname).is_loopback
    except ValueError:
        return False


def _redirect_blocker():
    class NoRedirect(request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise LocalModelError("local_model_redirect_blocked")
    return NoRedirect()


from ipaddress import ip_address


class _Completions:
    def __init__(self, client):
        self._client = client

    def create(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_completion_tokens: int = 1024,
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
        include_reasoning: bool | None = None,
        **_ignored,
    ):
        if model != self._client.model:
            raise LocalModelError("local_model_name_mismatch")
        if not isinstance(messages, list) or not messages:
            raise LocalModelError("local_model_messages_invalid")
        token_limit = max_tokens if max_tokens is not None else max_completion_tokens
        if not isinstance(token_limit, int) or isinstance(token_limit, bool) or not 1 <= token_limit <= 8192:
            raise LocalModelError("local_model_token_limit_invalid")
        if not isinstance(temperature, (int, float)) or isinstance(temperature, bool) or not 0 <= temperature <= 2:
            raise LocalModelError("local_model_temperature_invalid")

        if self._client.protocol == "ollama":
            url = self._client.base_url + "/api/chat"
            payload = {
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": float(temperature), "num_predict": token_limit},
            }
        else:
            url = self._client.base_url + "/chat/completions"
            payload = {
                "model": model,
                "messages": messages,
                "temperature": float(temperature),
                "max_tokens": token_limit,
                "stream": False,
            }

        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        req = request.Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with self._client.opener.open(req, timeout=self._client.timeout) as response:
                raw = response.read(2_000_001)
        except LocalModelError:
            raise
        except error.HTTPError as exc:
            raise LocalModelError(f"local_model_http_{exc.code}") from None
        except Exception as exc:
            raise LocalModelError(f"local_model_request_{type(exc).__name__}") from None
        if len(raw) > 2_000_000:
            raise LocalModelError("local_model_response_too_large")
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise LocalModelError("local_model_response_invalid_json") from None

        if self._client.protocol == "ollama":
            content = data.get("message", {}).get("content") if isinstance(data, dict) else None
        else:
            try:
                content = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError):
                content = None
        if not isinstance(content, str) or not content.strip():
            raise LocalModelError("local_model_response_content_missing")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


class _Chat:
    def __init__(self, client):
        self.completions = _Completions(client)


class LocalModelClient:
    def __init__(self, base_url: str, model: str, protocol: str, timeout: float = 60.0):
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "http"
            or not _is_loopback(parsed.hostname or "")
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or not model
            or protocol not in {"ollama", "openai-compatible"}
        ):
            raise LocalModelError("local_model_endpoint_not_allowed")
        if any(part == ".." for part in parsed.path.split("/")):
            raise LocalModelError("local_model_endpoint_path_invalid")
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 1 <= timeout <= 120:
            raise LocalModelError("local_model_timeout_invalid")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.protocol = protocol
        self.timeout = float(timeout)
        self.opener = request.build_opener(_redirect_blocker())
        self.chat = _Chat(self)


def create_local_model_client_from_env():
    base_url = os.environ.get("RSI_LOCAL_MODEL_BASE_URL", "").strip()
    model = os.environ.get("RSI_LOCAL_MODEL_NAME", "").strip()
    protocol = os.environ.get("RSI_LOCAL_MODEL_PROTOCOL", "").strip().lower()
    if not base_url or not model or not protocol:
        raise LocalModelError("local_model_configuration_missing")
    try:
        timeout = float(os.environ.get("RSI_LOCAL_MODEL_TIMEOUT", "60"))
    except ValueError:
        raise LocalModelError("local_model_timeout_invalid") from None
    return LocalModelClient(base_url, model, protocol, timeout)
