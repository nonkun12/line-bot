"""Tests for the provider-neutral domain service boundary."""

from core.distributed_services import build_domain_registry
from core.multi_agent import AgentRole


def test_build_domain_registry_wires_explicit_services():
    registry = build_domain_registry({
        AgentRole.VOICE: lambda task: "voice response",
        AgentRole.ENGLISH: lambda task: "english response",
        AgentRole.STOCKS: lambda task: "stocks response",
        AgentRole.NEWS: lambda task: "news response",
    })

    mapping = registry.build()
    assert set(mapping) == {
        AgentRole.VOICE,
        AgentRole.ENGLISH,
        AgentRole.STOCKS,
        AgentRole.NEWS,
    }
