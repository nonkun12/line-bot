from __future__ import annotations

import pytest

import core.provider_failover as provider_module
from core.provider_failover import ProviderFailover
import agents.normal.node as normal_node


def test_provider_failover_uses_groq_when_gemini_is_unavailable(monkeypatch):
    failover = ProviderFailover(cooldown_seconds=60)
    monkeypatch.setattr(normal_node, "provider_failover", failover)
    monkeypatch.setattr(normal_node, "call_gemini_via_n8n", lambda **kwargs: (_ for _ in ()).throw(normal_node.GeminiN8nError("429")))
    monkeypatch.setattr(normal_node, "handle_normal_message", lambda *args: "groq-ok")
    monkeypatch.delenv("AI_PROVIDER_PRIMARY", raising=False)
    monkeypatch.delenv("NORMAL_AGENT_PROVIDER", raising=False)

    reply, provider = normal_node._run_normal_generation({}, "hello", "user1", lambda *args: "")

    assert reply == "groq-ok"
    assert provider == "groq"
    assert failover.available("gemini") is False
    assert failover.available("groq") is True


def test_provider_failover_stops_when_both_providers_are_unavailable(monkeypatch):
    failover = ProviderFailover(cooldown_seconds=60)
    failover.mark_failure("gemini")
    failover.mark_failure("groq")
    monkeypatch.setattr(normal_node, "provider_failover", failover)

    reply, provider = normal_node._run_normal_generation({}, "hello", "user1", lambda *args: "")

    assert provider == "failover_exhausted"
    assert "両方が現在利用できません" in reply


def test_provider_recovers_after_cooldown(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(provider_module.time, "monotonic", lambda: now[0])
    failover = ProviderFailover(cooldown_seconds=10)

    failover.mark_failure("gemini")
    assert failover.ordered("gemini") == ("groq",)

    now[0] = 111.0
    assert failover.ordered("gemini") == ("gemini", "groq")


def test_gemini_success_clears_unavailable_state(monkeypatch):
    failover = ProviderFailover(cooldown_seconds=60)
    failover.mark_failure("gemini")
    monkeypatch.setattr(normal_node, "provider_failover", failover)
    monkeypatch.setattr(normal_node, "call_gemini_via_n8n", lambda **kwargs: {"reply": "gemini-ok"})
    monkeypatch.setattr(normal_node, "handle_normal_message", lambda *args: pytest.fail("Groq should not be called"))
    monkeypatch.delenv("AI_PROVIDER_PRIMARY", raising=False)
    monkeypatch.delenv("NORMAL_AGENT_PROVIDER", raising=False)

    failover.mark_success("gemini")
    reply, provider = normal_node._run_normal_generation({}, "hello", "user1", lambda *args: "")

    assert reply == "gemini-ok"
    assert provider == "gemini"
    assert failover.available("gemini") is True
