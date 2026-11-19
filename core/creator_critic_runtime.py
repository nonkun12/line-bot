"""Real-model adapter for the provider-neutral Creator/Critic pair.

The Creator/Critic contracts remain provider-neutral; this module is the thin
boundary that connects them to the existing Groq configuration. Secrets stay
in environment variables and are never passed through the agent contracts.
"""
from __future__ import annotations

import os
from typing import Callable

from groq import Groq

from .creator_critic import CriticAgent, CreatorAgent, CreatorCriticLoop, ModelCall

DEFAULT_MODEL = "openai/gpt-oss-20b"


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


def build_creator_critic_loop(
    *,
    model_call: ModelCall | None = None,
    max_iterations: int = 3,
) -> CreatorCriticLoop:
    """Build a real-model Creator -> evidence -> Critic loop.

    ``model_call`` is injectable for deterministic tests. Production callers
    can omit it and use the configured Groq model.
    """
    call: Callable[[str], str] = model_call or groq_model_call
    creator = CreatorAgent(call)
    critic = CriticAgent(call)
    return CreatorCriticLoop(creator, critic, max_iterations=max_iterations)


__all__ = ["DEFAULT_MODEL", "build_creator_critic_loop", "groq_model_call"]
