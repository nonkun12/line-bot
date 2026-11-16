"""Concrete loopback-only Creator/Critic model wiring for RSI -> REA.

The factory binds two separately configured Ollama clients. It supplies no
evidence trust root: callers must still inject an independent evidence verifier.
Model output remains proposal/review text and grants no execution authority.
"""
from __future__ import annotations

from dataclasses import dataclass

from .ai_factory_stage132_local_models import LocalModelConfig, OllamaLoopbackClient
from .creator_critic import CreatorAgent, CriticAgent


@dataclass(frozen=True)
class LoopbackREAAgents:
    creator: CreatorAgent
    critic: CriticAgent
    creator_model: str
    critic_model: str


def build_loopback_rea_agents(
    *, creator_model: str, critic_model: str,
    timeout_seconds: float = 30.0,
) -> LoopbackREAAgents:
    """Build two independent local Ollama-backed REA roles.

    Both endpoints are pinned to 127.0.0.1; remote URLs, paid APIs, tools,
    shell execution, and fallback providers are not configurable here.
    """
    if not isinstance(creator_model, str) or not creator_model.strip():
        raise ValueError("creator_model is required")
    if not isinstance(critic_model, str) or not critic_model.strip():
        raise ValueError("critic_model is required")
    if creator_model.strip() == critic_model.strip():
        raise ValueError("Creator and Critic must use distinct local model identities")
    creator_client = OllamaLoopbackClient(LocalModelConfig(
        model=creator_model.strip(),
        base_url="http://127.0.0.1:11434",
        timeout_seconds=timeout_seconds,
        max_output_tokens=768,
        think=False,
    ))
    critic_client = OllamaLoopbackClient(LocalModelConfig(
        model=critic_model.strip(),
        base_url="http://127.0.0.1:11434",
        timeout_seconds=timeout_seconds,
        max_output_tokens=768,
        think=False,
    ))

    def creator_call(prompt: str) -> str:
        return creator_client.chat(
            system="You are the bounded REA Creator. Produce one minimal, testable proposal only. Never claim evidence or grant authority.",
            prompt=prompt,
        )

    def critic_call(prompt: str) -> str:
        return critic_client.chat(
            system="You are the independent REA Critic. Assess only the supplied candidate and evidence. Never grant execution, patch, merge, deploy, or HOLD-release authority.",
            prompt=prompt,
        )

    return LoopbackREAAgents(
        creator=CreatorAgent(creator_call),
        critic=CriticAgent(critic_call),
        creator_model=creator_model.strip(),
        critic_model=critic_model.strip(),
    )


__all__ = ["LoopbackREAAgents", "build_loopback_rea_agents"]
