"""Single fail-closed capability gate for every Specialist dispatch path.

This module is the ONLY place that decides whether a specialist may run.
Every path that reaches ``agent.handle`` for a domain specialist (explicit
request_path handlers, the multi-specialist path, DistributedAgentCoordinator,
the bridge/executor adapters, ManagementAI and the Core graph) calls into it
with the *final* role/name that is about to execute.

Policy
------
* The decision is derived from ``management_contract.specialist_boundary``
  (the declared, immutable boundary) plus ``REQUIRED_CAPABILITY`` below.
* Anything unknown, unmapped, or not approved raises ``SpecialistGateError``
  (a ``RuntimeError`` so existing ``pytest.raises(RuntimeError)`` keeps working).
* The gate never grants, adds, or widens a capability.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import TypeVar

from .management_contract import Specialist, specialist_boundary
from .multi_agent import AgentRole

T = TypeVar("T")


class SpecialistGateError(RuntimeError):
    """A specialist dispatch was rejected by the Management capability gate."""


# Capability that must be declared in the specialist's boundary. A specialist
# missing from this table is rejected ("missing capability mapping").
REQUIRED_CAPABILITY: Mapping[Specialist, str] = MappingProxyType(
    {
        Specialist.GENERAL: "conversation",
        Specialist.VOICE: "text_to_speech",
        Specialist.ENGLISH: "english_learning",
        Specialist.NEWS: "news_retrieval",
        Specialist.STOCKS: "stock_quotes",
        Specialist.MARKET: "market_summary",
        Specialist.JOBS: "job_search",
        Specialist.MUSIC: "music_planning",
        Specialist.VIDEO: "video_planning",
        Specialist.WEB: "web_planning",
    }
)

# Canonical Core-registry agent name for each domain specialist.
DOMAIN_AGENT_NAMES: Mapping[Specialist, str] = MappingProxyType(
    {
        Specialist.VOICE: "voice",
        Specialist.ENGLISH: "english_learning",
        Specialist.NEWS: "ai_news",
        Specialist.STOCKS: "stocks",
        Specialist.MARKET: "global_market",
        Specialist.JOBS: "job_seeking",
        Specialist.MUSIC: "music",
        Specialist.VIDEO: "video",
    }
)

_AGENT_NAME_TO_SPECIALIST: Mapping[str, Specialist] = MappingProxyType(
    {name: specialist for specialist, name in DOMAIN_AGENT_NAMES.items()}
)


def resolve_specialist(value: Specialist | AgentRole | str) -> Specialist:
    """Normalize a Specialist / AgentRole / name into a ``Specialist``.

    Accepts the canonical values (``news``) and Core registry agent names
    (``ai_news``, ``job_seeking`` ...). Matching is exact; anything else is
    rejected rather than guessed.
    """
    if isinstance(value, Specialist):
        return value
    if isinstance(value, AgentRole):
        key = value.value
    elif isinstance(value, str):
        key = value
    else:
        raise SpecialistGateError(f"unknown specialist: {value!r}")
    alias = _AGENT_NAME_TO_SPECIALIST.get(key)
    if alias is not None:
        return alias
    try:
        return Specialist(key)
    except ValueError:
        raise SpecialistGateError(f"unknown specialist: {key}") from None


def assert_specialist_approved(value: Specialist | AgentRole | str) -> Specialist:
    """Return the canonical Specialist, or raise if it is not approved."""
    specialist = resolve_specialist(value)
    required = REQUIRED_CAPABILITY.get(specialist)
    if required is None:
        raise SpecialistGateError(f"missing capability mapping: {specialist.value}")
    try:
        boundary = specialist_boundary(specialist)
    except Exception as exc:  # incl. StopIteration for an unregistered boundary
        raise SpecialistGateError(
            f"specialist boundary unavailable: {specialist.value}"
        ) from exc
    if getattr(boundary, "specialist", None) is not specialist:
        raise SpecialistGateError(f"specialist boundary mismatch: {specialist.value}")
    if required not in tuple(boundary.capabilities):
        raise SpecialistGateError(
            f"specialist capability not approved: {specialist.value}:{required}"
        )
    return specialist


def assert_all_approved(
    values: Iterable[Specialist | AgentRole | str],
) -> tuple[Specialist, ...]:
    """Validate every entry before returning (all-or-nothing, no partial pass)."""
    return tuple(assert_specialist_approved(value) for value in tuple(values))


def is_specialist_approved(value: Specialist | AgentRole | str) -> bool:
    try:
        assert_specialist_approved(value)
    except SpecialistGateError:
        return False
    return True


def approved_executors(executors: Mapping[AgentRole, T]) -> dict[AgentRole, T]:
    """Drop executors whose role is unknown or not approved (never raises)."""
    return {
        role: executor
        for role, executor in executors.items()
        if is_specialist_approved(role)
    }


def assert_agent_approved(agent_name: str) -> None:
    """Gate a Core-registry agent by name right before it executes.

    Only domain specialist agents are governed by Management capabilities.
    Other registry agents (weather, notes, github, ...) are out of scope for
    this gate and pass through unchanged.
    """
    if not isinstance(agent_name, str) or not agent_name.strip():
        raise SpecialistGateError("agent name is required")
    specialist = _AGENT_NAME_TO_SPECIALIST.get(agent_name)
    if specialist is not None:
        assert_specialist_approved(specialist)


__all__ = [
    "DOMAIN_AGENT_NAMES",
    "REQUIRED_CAPABILITY",
    "SpecialistGateError",
    "approved_executors",
    "assert_agent_approved",
    "assert_all_approved",
    "assert_specialist_approved",
    "is_specialist_approved",
    "resolve_specialist",
]