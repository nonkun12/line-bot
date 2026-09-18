from __future__ import annotations

from core.agents import AgentRegistry, AgentRequest, AgentResponse
from core.multi_agent import AgentRole, AgentTask
from core.specialist_executor import (
    ROLE_TO_AGENT_NAME,
    RegistrySpecialistExecutor,
    SpecialistExecutorFactory,
    build_registry_executors,
)


class FakeAgent:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = name
        self.priority = 1
        self.enabled = True
        self.requests: list[AgentRequest] = []

    def can_handle(self, request: AgentRequest) -> bool:
        return True

    def handle(self, request: AgentRequest) -> AgentResponse:
        self.requests.append(request)
        return AgentResponse(f"{self.name}: {request.message}")


def test_factory_maps_existing_registry_agents_to_specialist_roles() -> None:
    agents = [
        FakeAgent("normal"),
        FakeAgent("voice"),
        FakeAgent("english_learning"),
        FakeAgent("ai_news"),
        FakeAgent("stocks"),
        FakeAgent("job_seeking"),
    ]
    registry = AgentRegistry(agents)
    request = AgentRequest("u1", "original", channel="slack", metadata={"source": "test"})

    executors = build_registry_executors(registry, request)

    assert set(executors) == {
        AgentRole.GENERAL,
        AgentRole.VOICE,
        AgentRole.ENGLISH,
        AgentRole.NEWS,
        AgentRole.STOCKS,
        AgentRole.JOBS,
    }


def test_registry_specialist_executor_preserves_request_context_and_bounds_result() -> None:
    agent = FakeAgent("stocks")
    request = AgentRequest("u1", "original", channel="slack", metadata={"source": "test"})
    executor = RegistrySpecialistExecutor(agent, request)

    result = executor.execute(
        AgentTask(
            "stock-1",
            AgentRole.STOCKS,
            "Analyze AAPL.",
            resources=frozenset({"aapl"}),
        )
    )

    assert result.success
    assert result.task_id == "stock-1"
    assert result.changed_resources == frozenset()
    assert result.summary == "stocks: Analyze AAPL."
    assert agent.requests[0].user_id == "u1"
    assert agent.requests[0].channel == "slack"
    assert agent.requests[0].metadata["management_task_id"] == "stock-1"
    assert agent.requests[0].metadata["declared_resources"] == ["aapl"]


def test_factory_skips_specialists_not_registered_yet() -> None:
    registry = AgentRegistry([FakeAgent("normal"), FakeAgent("stocks")])
    executors = SpecialistExecutorFactory(registry).build(
        AgentRequest("u1", "株価を調べて")
    )
    assert set(executors) == {AgentRole.GENERAL, AgentRole.STOCKS}


def test_role_mapping_is_explicit() -> None:
    assert ROLE_TO_AGENT_NAME[AgentRole.NEWS] == "ai_news"
    assert ROLE_TO_AGENT_NAME[AgentRole.STOCKS] == "stocks"
    assert ROLE_TO_AGENT_NAME[AgentRole.JOBS] == "job_seeking"

def test_factory_maps_job_role_to_existing_job_seeking_agent() -> None:
    registry = AgentRegistry([FakeAgent("job_seeking")])
    executors = SpecialistExecutorFactory(registry).build(
        AgentRequest("u1", "求人を探して")
    )
    assert set(executors) == {AgentRole.JOBS}
