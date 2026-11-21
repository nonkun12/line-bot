"""Real-model adapter for the provider-neutral Creator/Critic pair.

The Creator/Critic contracts remain provider-neutral. Groq remains the
backward-compatible default; Creator and Critic may independently select
Bonsai or LFM through explicit loopback-only environment profiles. Secrets
stay in environment variables and are never passed through agent contracts.
"""
from __future__ import annotations

import os
from typing import Callable

from groq import Groq

from .creator_critic import CriticAgent, CreatorAgent, CreatorCriticLoop, ModelCall
from .local_model_profiles import load_local_model_profile, local_model_call

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

    ``model_call`` is injectable for deterministic tests. Otherwise set
    CREATOR_CRITIC_PROVIDER=groq|bonsai|lfm, or independently set
    CREATOR_CRITIC_CREATOR_PROVIDER and CREATOR_CRITIC_CRITIC_PROVIDER.
    Local profiles require CREATOR_CRITIC_BONSAI_* or CREATOR_CRITIC_LFM_*
    BASE_URL and MODEL values. Local endpoints are restricted to loopback.
    """
    if model_call is not None:
        creator_call = critic_call = model_call
    else:
        default_provider = os.environ.get("CREATOR_CRITIC_PROVIDER", "groq").strip().lower()
        creator_provider = os.environ.get(
            "CREATOR_CRITIC_CREATOR_PROVIDER", default_provider
        ).strip().lower()
        critic_provider = os.environ.get(
            "CREATOR_CRITIC_CRITIC_PROVIDER", default_provider
        ).strip().lower()

        def provider_call(provider: str) -> Callable[[str], str]:
            if provider == "groq":
                return groq_model_call
            if provider in {"bonsai", "lfm"}:
                profile = load_local_model_profile(provider)
                return lambda prompt: local_model_call(prompt, profile)
            raise ValueError("provider must be groq, bonsai, or lfm")

        creator_call = provider_call(creator_provider)
        critic_call = provider_call(critic_provider)

    creator = CreatorAgent(creator_call)
    critic = CriticAgent(critic_call)
    return CreatorCriticLoop(creator, critic, max_iterations=max_iterations)


__all__ = [
    "DEFAULT_MODEL",
    "build_creator_critic_loop",
    "groq_model_call",
    "load_local_model_profile",
    "local_model_call",
]
