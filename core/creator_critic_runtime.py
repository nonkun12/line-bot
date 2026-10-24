"""Real-model adapter for the provider-neutral Creator/Critic pair.

The Creator/Critic contracts remain provider-neutral; this module is the thin
boundary that connects them to the existing Groq configuration. Secrets stay
in environment variables and are never passed through the agent contracts.
"""
from __future__ import annotations

import json
import os
from typing import Callable
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.parse import urlparse

from groq import Groq

from .creator_critic import CriticAgent, CreatorAgent, CreatorCriticLoop, ModelCall

DEFAULT_MODEL = "openai/gpt-oss-20b"


class _RejectRedirects(HTTPRedirectHandler):
    """Prevent a loopback endpoint from redirecting prompts to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def groq_model_call(
    prompt: str,
    *,
    client: Groq | None = None,
    model: str | None = None,
) -> str:
    """Call the configured Groq model and return only the assistant text."""
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt is required")

    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if client is None and not api_key:
        raise RuntimeError("GROQ_API_KEY is required for Creator/Critic real-model execution")

    active_client = client or Groq(api_key=api_key, timeout=15.0, max_retries=1)
    active_model = (model or os.environ.get("CREATOR_CRITIC_MODEL") or DEFAULT_MODEL).strip()
    if not active_model:
        raise ValueError("model is required")

    response = active_client.chat.completions.create(
        model=active_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    choices = getattr(response, "choices", None) or []
    if not choices:
        raise RuntimeError("Groq returned no choices")
    message = getattr(choices[0], "message", None)
    text = getattr(message, "content", None)
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("Groq returned empty content")
    return text.strip()



def openai_compatible_model_call(
    prompt: str,
    *,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    timeout: float = 15.0,
) -> str:
    """Call a local OpenAI-compatible endpoint (for example, Bonsai MLX).

    No paid provider is contacted by this adapter. The caller must explicitly
    supply/configure the endpoint; secrets are read only from environment.
    """
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt is required")
    endpoint = (base_url or os.environ.get("CREATOR_CRITIC_BASE_URL") or "").strip().rstrip("/")
    if not endpoint:
        raise RuntimeError("CREATOR_CRITIC_BASE_URL is required for local model execution")
    parsed_endpoint = urlparse(endpoint)
    if (
        parsed_endpoint.scheme not in {"http", "https"}
        or parsed_endpoint.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed_endpoint.username is not None
        or parsed_endpoint.password is not None
        or parsed_endpoint.query
        or parsed_endpoint.fragment
    ):
        raise RuntimeError("local model endpoint must use a loopback URL")
    active_model = (model or os.environ.get("CREATOR_CRITIC_MODEL") or "").strip()
    if not active_model:
        raise RuntimeError("CREATOR_CRITIC_MODEL is required for local model execution")
    token = api_key if api_key is not None else os.environ.get("CREATOR_CRITIC_API_KEY", "")
    request_body = json.dumps({
        "model": active_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token.strip():
        headers["Authorization"] = f"Bearer {token.strip()}"
    request = Request(f"{endpoint}/chat/completions", data=request_body, headers=headers, method="POST")
    try:
        opener = build_opener(_RejectRedirects)
        with opener.open(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        # Avoid echoing endpoint details or response bodies into durable logs.
        raise RuntimeError(f"local model request failed: {type(exc).__name__}") from None
    choices = payload.get("choices") if isinstance(payload, dict) else None
    message = choices[0].get("message") if isinstance(choices, list) and choices and isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("local model returned empty content")
    return content.strip()


def build_creator_critic_loop(
    *,
    model_call: ModelCall | None = None,
    max_iterations: int = 3,
) -> CreatorCriticLoop:
    """Build a real-model Creator -> evidence -> Critic loop.

    ``model_call`` is injectable for deterministic tests. Production callers
    can omit it and use the configured Groq model.
    """
    if model_call is not None:
        call: Callable[[str], str] = model_call
    elif os.environ.get("CREATOR_CRITIC_BASE_URL", "").strip():
        call = openai_compatible_model_call
    else:
        call = groq_model_call
    creator = CreatorAgent(call)
    critic = CriticAgent(call)
    return CreatorCriticLoop(creator, critic, max_iterations=max_iterations)


__all__ = ["DEFAULT_MODEL", "build_creator_critic_loop", "groq_model_call", "openai_compatible_model_call"]
