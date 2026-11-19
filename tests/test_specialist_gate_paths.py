"""Path-level tests: the gate must hold on EVERY route that can execute a specialist."""
from __future__ import annotations

import pytest

from core import request_path
from core import specialist_gate as gate
from core.agents import AgentRegistry, AgentRequest, AgentResponse
from core.langgraph_runtime import build_core_graph
from core.management_bridge import run_management_request
from core.management_contract import (
    ManagementDecision,
    ManagementRequest,
    Specialist,
    SpecialistBoundary,
    specialist_boundary as real_boundary,
)
from core.management_ai import ManagementPlan, ManagementPlanner
from core.multi_agent import AgentResult, AgentRole, AgentTask
from core.router import AgentRouter
from core.specialist_gate import SpecialistGateError

# Real Core-registry agent names, keyed by canonical specialist.
AGENT_NAME = dict(gate.DOMAIN_AGENT_NAMES)


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


class Registry:
    """Core-registry stand-in exposing every domain specialist under its real name."""

    def __init__(self) -> None:
        self.agents = {name: RecordingAgent(name) for name in AGENT_NAME.values()}

    def get(self, name):
        return self.agents.get(name)

    def executed(self) -> list[str]:
        return sorted(n for n, a in self.agents.items() if a.calls)


@pytest.fixture
def registry(monkeypatch) -> Registry:
    reg = Registry()
    monkeypatch.setattr(request_path, "build_core_agent_registry", lambda: reg)
    return reg


def deny(monkeypatch, *denied: Specialist) -> None:
    def boundary(specialist):
        if specialist in denied:
            return SpecialistBoundary(specialist, ())
        return real_boundary(specialist)

    monkeypatch.setattr(gate, "specialist_boundary", boundary)


# One unambiguous single-intent message per specialist (asserted below).
SINGLE_MESSAGES = {
    Specialist.NEWS: "AI NEWSをテスト",
    Specialist.STOCKS: "株価をテスト",
    Specialist.ENGLISH: "英語をテスト",
    Specialist.VOICE: "音声をテスト",
    Specialist.MUSIC: "音楽をテスト",
    Specialist.VIDEO: "動画をテスト",
    Specialist.JOBS: "求人をテスト",
    Specialist.MARKET: "世界市場をテスト",
}


@pytest.mark.parametrize("specialist", list(SINGLE_MESSAGES))
def test_denied_specialist_raises_and_no_agent_runs_on_explicit_path(
    monkeypatch, registry, specialist
):
    message = SINGLE_MESSAGES[specialist]
    assert request_path._resolve_multi_specialist_plan(message) is None  # single intent
    deny(monkeypatch, specialist)
    required = gate.REQUIRED_CAPABILITY[specialist]
    with pytest.raises(
        SpecialistGateError,
        match=f"specialist capability not approved: {specialist.value}:{required}",
    ):
        request_path.run_core_request("user-1", message, channel="line")
    assert registry.executed() == []


@pytest.mark.parametrize("specialist", list(SINGLE_MESSAGES))
def test_approved_specialist_executes_only_its_own_agent(registry, specialist):
    result = request_path.run_core_request(
        "user-1", SINGLE_MESSAGES[specialist], channel="line"
    )
    assert result["specialists"] == [specialist.value]
    assert result["parallel"] is False and result["max_workers"] == 1
    assert registry.executed() == [AGENT_NAME[specialist]]


# Messages where the keyword router (route_instruction) disagrees with the
# explicit handler chosen by request_path. Before the fix the gated specialist
# and the executed specialist differed (or the request died on "general").
ROUTER_DISAGREES = [
    ("ドル円のニュース", Specialist.MARKET),  # router said NEWS
    ("為替を教えて", Specialist.MARKET),  # router said GENERAL
    ("日経の動向", Specialist.MARKET),
    ("履歴書を書いて", Specialist.JOBS),
    ("面接の練習をして", Specialist.JOBS),
    ("台本を書いて", Specialist.VIDEO),
]


@pytest.mark.parametrize(("message", "specialist"), ROUTER_DISAGREES)
def test_gated_role_equals_executed_role_even_when_router_disagrees(
    registry, message, specialist
):
    assert request_path._resolve_multi_specialist_plan(message) is None
    result = request_path.run_core_request("user-1", message, channel="line")
    assert result["route"] == f"distributed:{specialist.value}"
    assert registry.executed() == [AGENT_NAME[specialist]]


def test_revoking_the_router_pick_cannot_smuggle_execution(monkeypatch, registry):
    """Regression for C1: NEWS revoked, message handled as MARKET, router says NEWS."""
    deny(monkeypatch, Specialist.NEWS)
    result = request_path.run_core_request("user-1", "ドル円のニュース", channel="line")
    assert result["route"] == "distributed:market"
    assert registry.agents["ai_news"].calls == 0
    assert registry.executed() == ["global_market"]


def test_revoking_the_handler_role_blocks_even_if_router_would_pick_another(
    monkeypatch, registry
):
    deny(monkeypatch, Specialist.MARKET)
    with pytest.raises(SpecialistGateError, match="market:market_summary"):
        request_path.run_core_request("user-1", "ドル円のニュース", channel="line")
    assert registry.executed() == []


# ------------------------------------------------------------------ multi path


def test_multi_rule_plan_uses_canonical_names_and_registry_names(registry):
    """H2: rule plans say 'ai_news'; enum says 'news'; registry says 'ai_news'."""
    result = request_path.run_core_request("user-1", "AI NEWSと株価を教えて", channel="line")
    assert result["intent"] == "multi_specialist"
    assert result["specialists"] == ["news", "stocks"]
    assert result["route"] == "management:news+stocks"
    assert registry.executed() == ["ai_news", "stocks"]


def test_multi_domain_plan_resolves_real_registry_names(registry):
    """'news'/'english' used to KeyError against the real registry names."""
    result = request_path._run_multi_specialist_request(
        "u", "m", channel="line", metadata={}, specialists=("news", "english")
    )
    assert result["specialists"] == ["news", "english"]
    assert registry.executed() == ["ai_news", "english_learning"]


def test_multi_plan_with_one_denied_specialist_runs_nothing(monkeypatch, registry):
    deny(monkeypatch, Specialist.STOCKS)
    with pytest.raises(SpecialistGateError, match="stocks:stock_quotes"):
        request_path.run_core_request("user-1", "AI NEWSと株価を教えて", channel="line")
    assert registry.executed() == []


@pytest.mark.parametrize(
    "message",
    ["AI NEWSと天気を教えて", "AI NEWSと株価と天気を教えて"],
)
def test_multi_plan_containing_weather_fails_closed_before_any_execution(registry, message):
    """weather is not a Management specialist: rejected, never partially run."""
    with pytest.raises(SpecialistGateError, match="unknown specialist: weather"):
        request_path.run_core_request("user-1", message, channel="line")
    assert registry.executed() == []


@pytest.mark.parametrize(
    ("plan", "error"),
    [
        (("news", "news"), "duplicate specialist"),
        (("news", "ai_news"), "duplicate specialist"),
        (("news", "stocks", "english", "voice", "music"), "exceeds worker limit"),
        ((), "plan is empty"),
        (("news", "nonexistent"), "unknown specialist: nonexistent"),
    ],
)
def test_multi_plan_bounds_are_enforced_before_execution(registry, plan, error):
    with pytest.raises(RuntimeError, match=error):
        request_path._run_multi_specialist_request(
            "u", "m", channel="line", metadata={}, specialists=plan
        )
    assert registry.executed() == []


def test_multi_path_last_mile_gate_blocks_execution_if_boundary_changes(
    monkeypatch, registry
):
    """Boundary passes plan validation, then is revoked before execution begins."""
    budget = {"left": 2}  # exactly the two plan-validation lookups

    def boundary(specialist):
        if budget["left"] > 0:
            budget["left"] -= 1
            return real_boundary(specialist)
        return SpecialistBoundary(specialist, ())

    monkeypatch.setattr(gate, "specialist_boundary", boundary)
    with pytest.raises(RuntimeError, match="all multi-specialists failed"):
        request_path._run_multi_specialist_request(
            "u", "m", channel="line", metadata={}, specialists=("news", "stocks")
        )
    assert registry.executed() == []


def test_multi_path_never_exceeds_worker_limit_on_the_happy_path(registry):
    result = request_path._run_multi_specialist_request(
        "u",
        "m",
        channel="line",
        metadata={},
        specialists=("music", "video", "jobs", "market"),
    )
    assert result["max_workers"] == 4 and len(result["specialists"]) == 4


# --------------------------------------------------- Core graph (fall-through path)


def _state(next_agent: str) -> dict:
    return {
        "user_id": "u",
        "raw_message": "hello",
        "channel": "line",
        "metadata": {},
        "next_agent": next_agent,
    }


def test_core_graph_blocks_denied_domain_agent_before_handle(monkeypatch):
    agent = RecordingAgent("ai_news")
    graph = build_core_graph(AgentRegistry([agent]))
    deny(monkeypatch, Specialist.NEWS)
    with pytest.raises(SpecialistGateError, match="news:news_retrieval"):
        graph.invoke(_state("ai_news"))
    assert agent.calls == 0


def test_core_graph_runs_approved_domain_agent_and_non_specialist_agents(monkeypatch):
    news, weather = RecordingAgent("ai_news"), RecordingAgent("weather")
    graph = build_core_graph(AgentRegistry([news, weather]))
    deny(monkeypatch, Specialist.STOCKS)  # unrelated denial must not interfere
    assert graph.invoke(_state("ai_news"))["final_reply"] == "ai_news-ran"
    assert graph.invoke(_state("weather"))["final_reply"] == "weather-ran"


def test_core_graph_does_not_gate_out_of_scope_agents_even_if_all_specialists_denied(
    monkeypatch,
):
    weather = RecordingAgent("weather")
    graph = build_core_graph(AgentRegistry([weather]))
    deny(monkeypatch, *Specialist)
    assert graph.invoke(_state("weather"))["final_reply"] == "weather-ran"


def test_agent_router_gates_domain_agents(monkeypatch):
    agent = RecordingAgent("stocks")
    router = AgentRouter(AgentRegistry([agent]))
    request = AgentRequest("u", "m")
    deny(monkeypatch, Specialist.STOCKS)
    with pytest.raises(SpecialistGateError):
        router.route(request)
    with pytest.raises(SpecialistGateError):
        router.route_to("stocks", request)
    assert agent.calls == 0


def test_run_core_request_fallthrough_to_core_graph_is_gated(monkeypatch):
    """A message no explicit handler matches, but the Supervisor sends to 'stocks'."""
    agent = RecordingAgent("stocks")
    monkeypatch.setattr(
        request_path,
        "supervisor_node",
        lambda state: {**state, "intent": "stocks", "next_agent": "stocks"},
    )
    monkeypatch.setattr(
        request_path,
        "build_current_core_graph",
        lambda: build_core_graph(AgentRegistry([agent])),
    )
    message = "こんにちは"
    assert request_path._resolve_multi_specialist_plan(message) is None

    deny(monkeypatch, Specialist.STOCKS)
    with pytest.raises(SpecialistGateError, match="stocks:stock_quotes"):
        request_path.run_core_request("user-1", message, channel="line")
    assert agent.calls == 0


# ------------------------------------------------ Management AI (main path) + fallback


class _StaticPlanner(ManagementPlanner):
    def __init__(self) -> None:
        self.calls = 0

    def plan(self, request: ManagementRequest, decision: ManagementDecision, feedback=()):
        self.calls += 1
        return ManagementPlan(
            "multi",
            decision,
            (
                AgentTask("news-task", AgentRole.NEWS, "news", resources=frozenset({"n"})),
                AgentTask("stocks-task", AgentRole.STOCKS, "stocks", resources=frozenset({"s"})),
            ),
        )


class _RecExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, task: AgentTask) -> AgentResult:
        self.calls += 1
        return AgentResult(task.task_id, True, "ok")


@pytest.fixture
def management(monkeypatch):
    executors = {AgentRole.NEWS: _RecExecutor(), AgentRole.STOCKS: _RecExecutor()}
    monkeypatch.setattr("core.management_bridge.build_core_agent_registry", lambda: object())
    monkeypatch.setattr(
        "core.management_bridge.build_registry_executors", lambda registry, request: executors
    )
    return executors


MANAGEMENT_MESSAGE = "AIニュースと株価を調べて"


def test_management_path_denial_raises_without_planning_or_execution(monkeypatch, management):
    deny(monkeypatch, Specialist.NEWS)
    planner = _StaticPlanner()
    with pytest.raises(SpecialistGateError, match="news:news_retrieval"):
        run_management_request("u1", MANAGEMENT_MESSAGE, planner=planner)
    assert planner.calls == 0  # no model call for a denied specialist
    assert [e.calls for e in management.values()] == [0, 0]


def test_management_path_denial_is_not_converted_into_a_legacy_fallback(
    monkeypatch, management
):
    """A gate denial must surface; returning None would trigger the legacy route."""
    deny(monkeypatch, Specialist.STOCKS)
    try:
        outcome = run_management_request("u1", MANAGEMENT_MESSAGE, planner=_StaticPlanner())
    except SpecialistGateError:
        return
    pytest.fail(f"gate denial was swallowed (returned {outcome!r})")


def test_management_path_happy_path_still_works(management):
    reply = run_management_request("u1", MANAGEMENT_MESSAGE, planner=_StaticPlanner())
    assert reply == "【AI NEWS】\nok\n\n【Stocks】\nok"


def test_gate_denial_raised_by_manager_run_is_not_swallowed(monkeypatch, management):
    """Denial that only appears at plan time (after the up-front check) still raises."""
    calls = {"n": 0}

    def boundary(specialist):
        calls["n"] += 1
        # up-front check (2 roles) and ManagementAI.__init__ filter (2 roles) pass...
        if calls["n"] <= 4:
            return real_boundary(specialist)
        return SpecialistBoundary(specialist, ())  # ...revoked before plan execution

    monkeypatch.setattr(gate, "specialist_boundary", boundary)
    with pytest.raises(SpecialistGateError):
        run_management_request("u1", MANAGEMENT_MESSAGE, planner=_StaticPlanner())
    assert [e.calls for e in management.values()] == [0, 0]


def test_legacy_fallback_after_management_failure_is_still_gated(monkeypatch, registry):
    """Management fails (allowed -> None); the run_core_request fallback re-applies the gate."""
    monkeypatch.setattr("core.management_bridge.build_core_agent_registry", lambda: object())
    monkeypatch.setattr(
        "core.management_bridge.build_registry_executors",
        lambda reg, req: {AgentRole.NEWS: _RecExecutor(), AgentRole.STOCKS: _RecExecutor()},
    )

    class Broken(_StaticPlanner):
        def plan(self, request, decision, feedback=()):
            raise RuntimeError("temporary planner outage")

    assert run_management_request("u1", MANAGEMENT_MESSAGE, planner=Broken()) is None

    deny(monkeypatch, Specialist.NEWS)  # policy tightened before the fallback runs
    with pytest.raises(SpecialistGateError, match="news:news_retrieval"):
        request_path.run_core_request("u1", MANAGEMENT_MESSAGE, channel="line")
    assert registry.executed() == []