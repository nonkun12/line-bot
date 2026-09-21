"""Unit/contract tests for the single fail-closed Specialist capability gate."""
from __future__ import annotations

import pytest

from core import specialist_gate as gate
from core.agents import AgentRegistry, AgentRequest, AgentResponse
from core.distributed_execution_artifact import ExecutionArtifact, StaticExecutionArtifactProvider
from core.distributed_agent_bridge import _AGENT_NAMES, build_agent_registry
from core.distributed_agent_catalog import DISTRIBUTED_AGENT_CATALOG
from core.distributed_agent_versions import DistributedAgentVersion, DistributedAgentVersionRegistry, catalog_digest
from core.distributed_execution_gate import ExecutionIdentity
from core.distributed_coordinator import DistributedAgentCoordinator
from core.management_ai import PLANNABLE_ROLES, ManagementAI, ManagementPlan
from core.management_bridge import SUPPORTED_MULTI_SPECIALISTS
from core.management_contract import (
    ManagementDecision,
    Specialist,
    SpecialistBoundary,
    default_specialist_boundaries,
    specialist_boundary as real_boundary,
)
from core.multi_agent import AgentResult, AgentRole, AgentTask
from core.specialist_executor import (
    ROLE_TO_AGENT_NAME,
    RegistrySpecialistExecutor,
    SpecialistExecutorFactory,
)
from core.specialist_gate import SpecialistGateError

DEV_ROLES = frozenset(
    {
        AgentRole.MANAGER,
        AgentRole.IMPLEMENTER,
        AgentRole.TESTER,
        AgentRole.DEBUGGER,
        AgentRole.REFACTORER,
        AgentRole.REVIEWER,
        AgentRole.REPAIRER,
        AgentRole.INTEGRATOR,
    }
)


def deny(monkeypatch, *denied: Specialist) -> None:
    """Strip every capability from ``denied``; all others keep their real boundary."""

    def boundary(specialist):
        if specialist in denied:
            return SpecialistBoundary(specialist, ())
        return real_boundary(specialist)

    monkeypatch.setattr(gate, "specialist_boundary", boundary)


class RecordingAgent:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = name
        self.priority = 1
        self.enabled = True
        self.calls = 0

    def can_handle(self, request) -> bool:
        return True

    def handle(self, request) -> AgentResponse:
        self.calls += 1
        return AgentResponse(f"{self.name}-ran")


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[AgentTask] = []

    def execute(self, task: AgentTask) -> AgentResult:
        self.calls.append(task)
        return AgentResult(task.task_id, True, "ok")


# --------------------------------------------------------------------- gate core


@pytest.mark.parametrize("specialist", list(gate.REQUIRED_CAPABILITY))
def test_gate_denies_each_specialist_without_capability(monkeypatch, specialist):
    deny(monkeypatch, specialist)
    required = gate.REQUIRED_CAPABILITY[specialist]
    with pytest.raises(
        SpecialistGateError,
        match=f"specialist capability not approved: {specialist.value}:{required}",
    ):
        gate.assert_specialist_approved(specialist)


def test_gate_error_is_runtime_error_for_backward_compatibility():
    assert issubclass(SpecialistGateError, RuntimeError)


@pytest.mark.parametrize(
    "value",
    ["weather", "", " news", "News", "implementer", "manager", "nonexistent", None, 42],
)
def test_unknown_specialist_fails_closed(value):
    with pytest.raises(SpecialistGateError, match="unknown specialist"):
        gate.assert_specialist_approved(value)


@pytest.mark.parametrize("role", sorted(DEV_ROLES, key=lambda r: r.value))
def test_development_roles_are_not_specialists(role):
    with pytest.raises(SpecialistGateError, match="unknown specialist"):
        gate.assert_specialist_approved(role)


@pytest.mark.parametrize(
    ("alias", "expected"),
    [
        ("ai_news", Specialist.NEWS),
        ("news", Specialist.NEWS),
        ("english_learning", Specialist.ENGLISH),
        ("job_seeking", Specialist.JOBS),
        ("global_market", Specialist.MARKET),
        (AgentRole.STOCKS, Specialist.STOCKS),
        (Specialist.VIDEO, Specialist.VIDEO),
    ],
)
def test_names_normalize_to_one_canonical_specialist(alias, expected):
    assert gate.resolve_specialist(alias) is expected
    assert gate.assert_specialist_approved(alias) is expected


def test_missing_capability_mapping_fails_closed(monkeypatch):
    monkeypatch.setattr(
        gate,
        "REQUIRED_CAPABILITY",
        {k: v for k, v in gate.REQUIRED_CAPABILITY.items() if k is not Specialist.NEWS},
    )
    with pytest.raises(SpecialistGateError, match="missing capability mapping: news"):
        gate.assert_specialist_approved(Specialist.NEWS)


def test_boundary_lookup_failure_fails_closed_not_stop_iteration(monkeypatch):
    def broken(_specialist):
        raise StopIteration

    monkeypatch.setattr(gate, "specialist_boundary", broken)
    with pytest.raises(SpecialistGateError, match="boundary unavailable"):
        gate.assert_specialist_approved(Specialist.NEWS)


def test_boundary_for_a_different_specialist_is_rejected(monkeypatch):
    monkeypatch.setattr(
        gate,
        "specialist_boundary",
        lambda _s: real_boundary(Specialist.STOCKS),
    )
    with pytest.raises(SpecialistGateError, match="boundary mismatch"):
        gate.assert_specialist_approved(Specialist.NEWS)


def test_assert_all_approved_is_all_or_nothing(monkeypatch):
    deny(monkeypatch, Specialist.STOCKS)
    with pytest.raises(SpecialistGateError):
        gate.assert_all_approved([Specialist.NEWS, Specialist.STOCKS])


def test_agent_gate_only_governs_domain_agents(monkeypatch):
    deny(monkeypatch, Specialist.NEWS)
    with pytest.raises(SpecialistGateError):
        gate.assert_agent_approved("ai_news")
    for out_of_scope in ("weather", "normal", "notes", "github"):
        gate.assert_agent_approved(out_of_scope)  # not a Management specialist
    with pytest.raises(SpecialistGateError, match="agent name is required"):
        gate.assert_agent_approved("")


def test_approved_executors_drops_denied_and_non_specialist_roles(monkeypatch):
    deny(monkeypatch, Specialist.NEWS)
    executors = {
        AgentRole.NEWS: object(),
        AgentRole.STOCKS: object(),
        AgentRole.IMPLEMENTER: object(),
    }
    assert set(gate.approved_executors(executors)) == {AgentRole.STOCKS}


# ------------------------------------------- single source of truth / drift guards


def test_every_specialist_has_a_required_capability_declared_in_its_boundary():
    assert set(gate.REQUIRED_CAPABILITY) == set(Specialist)
    for boundary in default_specialist_boundaries():
        assert gate.REQUIRED_CAPABILITY[boundary.specialist] in boundary.capabilities


def test_every_agent_role_is_classified_as_specialist_or_development():
    specialist_values = {s.value for s in Specialist}
    for role in AgentRole:
        assert (role.value in specialist_values) != (role in DEV_ROLES), (
            f"AgentRole.{role.name} must be classified as a specialist or a dev role"
        )


def test_role_and_agent_name_tables_agree_with_the_gate():
    domain = {AgentRole(s.value): name for s, name in gate.DOMAIN_AGENT_NAMES.items()}
    assert dict(_AGENT_NAMES) == domain
    assert {r: n for r, n in ROLE_TO_AGENT_NAME.items() if r is not AgentRole.GENERAL} == domain
    assert PLANNABLE_ROLES == {AgentRole(s.value) for s in Specialist}
    assert SUPPORTED_MULTI_SPECIALISTS == PLANNABLE_ROLES - {AgentRole.GENERAL}


def test_domain_agent_names_exist_in_the_real_core_registry():
    from graph.core_registry import build_core_agent_registry

    registry = build_core_agent_registry()
    for name in gate.DOMAIN_AGENT_NAMES.values():
        assert registry.get(name).name == name


# ------------------------------------------------------------------- coordinator


def test_coordinator_gates_final_role_before_any_executor_runs(monkeypatch):
    deny(monkeypatch, Specialist.NEWS)
    executor = RecordingExecutor()
    coordinator = DistributedAgentCoordinator({AgentRole.NEWS: executor})
    with pytest.raises(SpecialistGateError, match="news:news_retrieval"):
        coordinator.dispatch("req", "AI NEWSを調べて")
    assert executor.calls == []


def test_explicit_role_bypasses_router_so_gated_role_is_the_executed_role():
    news, market = RecordingExecutor(), RecordingExecutor()
    coordinator = DistributedAgentCoordinator(
        {AgentRole.NEWS: news, AgentRole.MARKET: market}
    )
    # route_instruction() would pick NEWS ("ニュース") for this message.
    report = coordinator.dispatch("req", "ドル円のニュース", expected_role=AgentRole.MARKET)
    assert report.decision.role is AgentRole.MARKET
    assert report.contract.task.role is AgentRole.MARKET
    assert len(market.calls) == 1 and news.calls == []


def test_denying_the_router_pick_does_not_block_or_leak_the_explicit_role(monkeypatch):
    deny(monkeypatch, Specialist.NEWS)  # router would have picked NEWS
    news, market = RecordingExecutor(), RecordingExecutor()
    coordinator = DistributedAgentCoordinator(
        {AgentRole.NEWS: news, AgentRole.MARKET: market}
    )
    coordinator.dispatch("req", "ドル円のニュース", expected_role=AgentRole.MARKET)
    assert len(market.calls) == 1 and news.calls == []


def test_explicit_role_that_is_denied_never_reaches_an_executor(monkeypatch):
    deny(monkeypatch, Specialist.MARKET)
    news, market = RecordingExecutor(), RecordingExecutor()
    coordinator = DistributedAgentCoordinator(
        {AgentRole.NEWS: news, AgentRole.MARKET: market}
    )
    with pytest.raises(SpecialistGateError, match="market:market_summary"):
        coordinator.dispatch("req", "ドル円のニュース", expected_role=AgentRole.MARKET)
    assert news.calls == [] and market.calls == []


def test_coordinator_rejects_non_specialist_explicit_roles():
    executor = RecordingExecutor()
    coordinator = DistributedAgentCoordinator({AgentRole.IMPLEMENTER: executor})
    with pytest.raises(SpecialistGateError, match="unknown specialist"):
        coordinator.dispatch("req", "do it", expected_role=AgentRole.IMPLEMENTER)
    with pytest.raises(TypeError):
        coordinator.dispatch("req", "do it", expected_role="news")  # type: ignore[arg-type]
    assert executor.calls == []


def test_one_dispatch_runs_exactly_one_task_on_one_executor():
    executors = {role: RecordingExecutor() for role in (AgentRole.NEWS, AgentRole.STOCKS)}
    coordinator = DistributedAgentCoordinator(executors)
    coordinator.dispatch("req", "AI NEWSと株価", expected_role=AgentRole.NEWS)
    assert [len(e.calls) for e in executors.values()] == [1, 0]


def test_router_path_keeps_missing_executor_fail_closed_for_general():
    report = DistributedAgentCoordinator({}).dispatch("req", "こんにちは")
    assert not report.success
    assert "missing executor for role: general" in (report.runtime.error or "")


# ---------------------------------------------- bridge / specialist_executor layers


class _BridgeRegistry:
    def __init__(self, agent):
        self._agent = agent

    def get(self, name):
        return self._agent if name == "ai_news" else None

def _bridge_execution_context():
    descriptor = next(item for item in DISTRIBUTED_AGENT_CATALOG if item.key == "ai_news")
    digest = catalog_digest(descriptor)
    version = DistributedAgentVersion(
        agent_key="ai_news",
        version="0.2.0",
        lifecycle=__import__("core.agent_specs", fromlist=["AgentLifecycle"]).AgentLifecycle.ENABLED,
        git_sha="a" * 40,
        catalog_digest=digest,
    )
    registry = DistributedAgentVersionRegistry([version])
    artifact = ExecutionArtifact(
        identity=ExecutionIdentity("ai_news", "0.2.0", "a" * 40, digest),
        artifact_id="test-ai-news",
    )
    return registry, StaticExecutionArtifactProvider((artifact,))


def test_bridge_handler_is_last_mile_gated(monkeypatch):
    agent = RecordingAgent("ai_news")
    version_registry, artifact_provider = _bridge_execution_context()
    executors = build_agent_registry(
        _BridgeRegistry(agent),
        version_registry=version_registry,
        artifact_provider=artifact_provider,
    ).build()
    deny(monkeypatch, Specialist.NEWS)
    with pytest.raises(SpecialistGateError):
        executors[AgentRole.NEWS].execute(AgentTask("t", AgentRole.NEWS, "AI NEWS"))
    assert agent.calls == 0


def test_bridge_executor_refuses_a_task_for_another_role():
    agent = RecordingAgent("ai_news")
    executors = build_agent_registry(_BridgeRegistry(agent)).build()
    with pytest.raises(RuntimeError, match="does not match executor role"):
        executors[AgentRole.NEWS].execute(AgentTask("t", AgentRole.MARKET, "x"))
    assert agent.calls == 0


def test_specialist_factory_never_builds_an_executor_for_a_denied_role(monkeypatch):
    deny(monkeypatch, Specialist.NEWS)
    registry = AgentRegistry([RecordingAgent("ai_news"), RecordingAgent("stocks")])
    executors = SpecialistExecutorFactory(registry).build(AgentRequest("u", "m"))
    assert set(executors) == {AgentRole.STOCKS}


def test_registry_specialist_executor_denies_at_execution_time(monkeypatch):
    agent = RecordingAgent("ai_news")
    executor = RegistrySpecialistExecutor(agent, AgentRequest("u", "m"))
    deny(monkeypatch, Specialist.NEWS)  # revoked after the executor was built
    result = executor.execute(AgentTask("t", AgentRole.NEWS, "AI NEWS"))
    assert not result.success
    assert "specialist capability not approved: news:news_retrieval" in result.summary
    assert agent.calls == 0


# ------------------------------------------------------------------ ManagementAI


class _TwoStepPlanner:
    """news -> stocks in two dependent batches (so partial execution is possible)."""

    def __init__(self) -> None:
        self.calls = 0

    def plan(self, request, decision, feedback=()):
        self.calls += 1
        return ManagementPlan(
            "two step",
            decision,
            (
                AgentTask("a", AgentRole.NEWS, "news", resources=frozenset({"r1"})),
                AgentTask(
                    "b",
                    AgentRole.STOCKS,
                    "stocks",
                    resources=frozenset({"r2"}),
                    depends_on=("a",),
                ),
            ),
        )


def _management_request():
    from core.management_contract import ManagementRequest

    return ManagementRequest("u1", "AIニュースと株価")


def test_management_ai_denies_whole_plan_before_running_any_task(monkeypatch):
    deny(monkeypatch, Specialist.STOCKS)  # the SECOND batch is denied
    news, stocks = RecordingExecutor(), RecordingExecutor()
    manager = ManagementAI(
        {AgentRole.NEWS: news, AgentRole.STOCKS: stocks}, planner=_TwoStepPlanner()
    )
    with pytest.raises(SpecialistGateError, match="stocks:stock_quotes"):
        manager.run(_management_request())
    assert news.calls == [] and stocks.calls == []  # no partial execution


def test_management_ai_never_keeps_an_executor_for_an_unapproved_role(monkeypatch):
    deny(monkeypatch, Specialist.NEWS)
    manager = ManagementAI(
        {AgentRole.NEWS: RecordingExecutor(), AgentRole.STOCKS: RecordingExecutor()},
        planner=_TwoStepPlanner(),
    )
    assert set(manager._executors) == {AgentRole.STOCKS}