from __future__ import annotations

from agents.stocks.node import StocksAgent
from core.agents import AgentRequest
from core.management_contract import ManagementDecision, ManagementRequest, Specialist
from core.management_ai import ManagementPlan, ManagementPlanner
from core.multi_agent import AgentResult, AgentRole, AgentTask
from core.management_bridge import (
    run_management_request,
    should_route_to_management_ai,
    specialist_roles_for_message,
)


def test_management_bridge_keeps_broad_world_market_request_on_market_ai() -> None:
    roles = specialist_roles_for_message("世界の株価と為替を教えて")
    assert roles == frozenset({AgentRole.MARKET})
    assert not should_route_to_management_ai("世界の株価と為替を教えて")


def test_management_bridge_detects_market_and_stocks_specialists() -> None:
    roles = specialist_roles_for_message("NYダウと株価を調べて")
    assert roles == frozenset({AgentRole.MARKET, AgentRole.STOCKS})
    assert should_route_to_management_ai("NYダウと株価を調べて")


def test_management_bridge_detects_multiple_specialists() -> None:
    roles = specialist_roles_for_message("AIニュースと株価を調べて")
    assert roles == frozenset({AgentRole.NEWS, AgentRole.STOCKS})
    assert should_route_to_management_ai("AIニュースと株価を調べて")


def test_management_bridge_detects_jobs_and_news_specialists() -> None:
    roles = specialist_roles_for_message("求人とAIニュースを調べて")
    assert roles == frozenset({AgentRole.JOBS, AgentRole.NEWS})
    assert should_route_to_management_ai("求人とAIニュースを調べて")


def test_management_bridge_detects_music_and_video_specialists() -> None:
    roles = specialist_roles_for_message("音楽のBGMと動画の絵コンテを作って")
    assert roles == frozenset({AgentRole.MUSIC, AgentRole.VIDEO})
    assert should_route_to_management_ai("音楽のBGMと動画の絵コンテを作って")


def test_management_bridge_keeps_single_specialist_on_existing_route() -> None:
    assert specialist_roles_for_message("今日の株価を教えて") == frozenset({AgentRole.STOCKS})
    assert not should_route_to_management_ai("今日の株価を教えて")


class StaticPlanner(ManagementPlanner):
    def plan(self, request: ManagementRequest, decision: ManagementDecision, feedback=()) -> ManagementPlan:
        return ManagementPlan(
            objective="multi specialist",
            decision=decision,
            tasks=(
                AgentTask(
                    "news-task",
                    AgentRole.NEWS,
                    "Collect recent AI news headlines.",
                    resources=frozenset({"news"}),
                ),
                AgentTask(
                    "stocks-task",
                    AgentRole.STOCKS,
                    "Summarize the requested stock data.",
                    resources=frozenset({"stocks"}),
                ),
            ),
            parallel_safe=False,
        )


class FakeExecutor:
    def __init__(self, role: AgentRole) -> None:
        self.role = role

    def execute(self, task: AgentTask) -> AgentResult:
        return AgentResult(task.task_id, True, f"{self.role.value} result")


class OutOfScopeDependencyPlanner(ManagementPlanner):
    def plan(self, request, decision, feedback=()):
        return ManagementPlan(
            objective="model emitted an out-of-scope dependency",
            decision=decision,
            tasks=(
                AgentTask(
                    "general-task",
                    AgentRole.GENERAL,
                    "General planning context.",
                    resources=frozenset({"general"}),
                ),
                AgentTask(
                    "english-task",
                    AgentRole.ENGLISH,
                    "Teach English.",
                    resources=frozenset({"english"}),
                    depends_on=("general-task",),
                ),
                AgentTask(
                    "music-task",
                    AgentRole.MUSIC,
                    "Plan music.",
                    resources=frozenset({"music"}),
                ),
            ),
        )


def test_management_bridge_replaces_out_of_scope_dependencies_without_widening_roles(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.management_bridge.build_core_agent_registry",
        lambda: object(),
    )
    seen: list[AgentTask] = []

    class RecordingExecutor(FakeExecutor):
        def execute(self, task: AgentTask) -> AgentResult:
            seen.append(task)
            return super().execute(task)

    monkeypatch.setattr(
        "core.management_bridge.build_registry_executors",
        lambda registry, request: {
            AgentRole.ENGLISH: RecordingExecutor(AgentRole.ENGLISH),
            AgentRole.MUSIC: RecordingExecutor(AgentRole.MUSIC),
        },
    )

    reply = run_management_request(
        "u1",
        "音楽作曲と英語の学習",
        planner=OutOfScopeDependencyPlanner(),
    )

    assert "【English】" in reply
    assert "【Music】" in reply
    assert {task.role for task in seen} == {AgentRole.ENGLISH, AgentRole.MUSIC}
    assert all("general-task" not in task.depends_on for task in seen)


def test_run_management_request_collects_specialist_results(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.management_bridge.build_core_agent_registry",
        lambda: object(),
    )
    monkeypatch.setattr(
        "core.management_bridge.build_registry_executors",
        lambda registry, request: {
            AgentRole.NEWS: FakeExecutor(AgentRole.NEWS),
            AgentRole.STOCKS: FakeExecutor(AgentRole.STOCKS),
        },
    )

    reply = run_management_request(
        "u1",
        "AIニュースと株価を調べて",
        channel="slack",
        planner=StaticPlanner(),
    )

    assert reply == "【AI NEWS】\nnews result\n\n【Stocks】\nstocks result"


def test_run_management_request_returns_none_for_ineligible_request() -> None:
    assert run_management_request(
        "u1",
        "英語を練習したい",
        planner=StaticPlanner(),
    ) is None



def test_run_management_request_falls_back_when_management_execution_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.management_bridge.build_core_agent_registry",
        lambda: object(),
    )
    monkeypatch.setattr(
        "core.management_bridge.build_registry_executors",
        lambda registry, request: {
            AgentRole.NEWS: FakeExecutor(AgentRole.NEWS),
            AgentRole.STOCKS: FakeExecutor(AgentRole.STOCKS),
        },
    )

    class BrokenPlanner(StaticPlanner):
        def plan(self, request, decision, feedback=()):
            raise RuntimeError("temporary planner outage")

    assert run_management_request(
        "u1",
        "AIニュースと株価を調べて",
        planner=BrokenPlanner(),
    ) is None



def test_ai_gateway_uses_management_bridge_for_multi_specialist_request(monkeypatch) -> None:
    import app as app_module
    from core.gateway import AIRequest

    calls = []

    monkeypatch.setattr(
        app_module,
        "run_management_request",
        lambda user_id, message, **kwargs: calls.append((user_id, message, kwargs)) or "管理AI統合結果",
    )
    monkeypatch.setattr(
        app_module,
        "run_core_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy core route should not run")),
    )

    response = app_module._handle_ai_gateway_request(
        AIRequest("u1", "AIニュースと株価を調べて", channel="slack")
    )

    assert response == "管理AI統合結果"
    assert calls and calls[0][0:2] == ("u1", "AIニュースと株価を調べて")


def test_ai_gateway_falls_back_to_core_when_management_returns_none(monkeypatch) -> None:
    import app as app_module
    from core.gateway import AIRequest

    monkeypatch.setattr(app_module, "run_management_request", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        app_module,
        "run_core_request",
        lambda *args, **kwargs: {"final_reply": "従来Core結果"},
    )
    monkeypatch.setattr(
        app_module,
        "extract_core_reply",
        lambda result: result["final_reply"],
    )

    response = app_module._handle_ai_gateway_request(
        AIRequest("u1", "AIニュースと株価を調べて", channel="slack")
    )

    assert response == "従来Core結果"


def test_run_management_request_does_not_retry_failed_execution(monkeypatch) -> None:
    class RaisingExecutor(FakeExecutor):
        def execute(self, task: AgentTask) -> AgentResult:
            raise RuntimeError("external side effect failed")

    monkeypatch.setattr(
        "core.management_bridge.build_core_agent_registry",
        lambda: object(),
    )
    monkeypatch.setattr(
        "core.management_bridge.build_registry_executors",
        lambda registry, request: {
            AgentRole.NEWS: RaisingExecutor(AgentRole.NEWS),
            AgentRole.STOCKS: FakeExecutor(AgentRole.STOCKS),
        },
    )

    reply = run_management_request(
        "u1",
        "AIニュースと株価を調べて",
        planner=StaticPlanner(),
    )

    assert reply == "管理AIの実行で問題が発生したため、同じ専門AIを再実行せずに処理を停止しました。"


def test_management_bridge_binds_stock_task_to_user_ticker(monkeypatch) -> None:
    from core.management_bridge import _bind_source_instructions

    monkeypatch.setattr(
        StocksAgent,
        "_resolve_ticker",
        classmethod(lambda cls, _message: ("7203.T", "トヨタ")),
    )
    plan = StaticPlanner().plan(
        ManagementRequest("u1", "AIニュースとトヨタ株価"),
        ManagementDecision(Specialist.NEWS, "multi", 0.95),
    )
    bound = _bind_source_instructions(plan, "AIニュースとトヨタ株価")
    instructions = {task.role: task.instruction for task in bound.tasks}
    assert instructions[AgentRole.NEWS] == "AI NEWS"
    assert instructions[AgentRole.STOCKS] == "ticker 7203.T"


def test_management_bridge_detects_news_and_toyota_stock_as_two_specialists() -> None:
    roles = specialist_roles_for_message("AI NEWSとトヨタの株価を教えて")
    assert roles == frozenset({AgentRole.NEWS, AgentRole.STOCKS})
    assert should_route_to_management_ai("AI NEWSとトヨタの株価を教えて")



def test_local_peer_review_is_explicitly_opt_in_and_uses_configured_loopback_model(monkeypatch):
    from types import SimpleNamespace
    from core.management_ai import ManagementAI

    monkeypatch.setenv("ORCHESTRATOR_LOCAL_PEER_REVIEW_ENABLED", "true")
    monkeypatch.setenv("ORCHESTRATOR_LOCAL_PEER_REVIEW_MODEL", "lfm3:1.7b-qad-q4_0")
    monkeypatch.setenv("ORCHESTRATOR_LOCAL_PEER_REVIEW_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setattr(
        "core.management_bridge.build_core_agent_registry",
        lambda: object(),
    )
    monkeypatch.setattr(
        "core.management_bridge.build_registry_executors",
        lambda registry, request: {
            AgentRole.NEWS: FakeExecutor(AgentRole.NEWS),
            AgentRole.STOCKS: FakeExecutor(AgentRole.STOCKS),
        },
    )
    captured = {}
    fake_run = SimpleNamespace(
        success=True,
        collaboration_snapshot=lambda: {"agent_count": 2, "accepted": True},
        observations=(),
    )

    class FakeManager:
        def run(self, request):
            return fake_run

    def fake_factory(cls, executors, **kwargs):
        captured.update(kwargs)
        return FakeManager()

    monkeypatch.setattr(ManagementAI, "with_local_peer_review", classmethod(fake_factory))
    monkeypatch.setattr(
        "core.management_bridge.record_collaboration_snapshot",
        lambda **kwargs: captured.update(audit=kwargs),
    )

    result = run_management_request(
        "u1",
        "AIニュースと株価を調べて",
        planner=StaticPlanner(),
    )

    assert result is None
    assert captured["model"] == "lfm3:1.7b-qad-q4_0"
    assert captured["base_url"] == "http://127.0.0.1:11434/v1"
    assert captured["audit"]["snapshot"]["agent_count"] == 2


def test_local_peer_review_enabled_without_model_fails_closed_before_execution(monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_LOCAL_PEER_REVIEW_ENABLED", "true")
    monkeypatch.delenv("ORCHESTRATOR_LOCAL_PEER_REVIEW_MODEL", raising=False)
    monkeypatch.setattr(
        "core.management_bridge.build_core_agent_registry",
        lambda: object(),
    )
    monkeypatch.setattr(
        "core.management_bridge.build_registry_executors",
        lambda registry, request: {
            AgentRole.NEWS: FakeExecutor(AgentRole.NEWS),
            AgentRole.STOCKS: FakeExecutor(AgentRole.STOCKS),
        },
    )

    result = run_management_request(
        "u1",
        "AIニュースと株価を調べて",
        planner=StaticPlanner(),
    )
    assert result == "管理AIの実行で問題が発生したため、同じ専門AIを再実行せずに処理を停止しました。"



def test_revision_workflow_is_off_by_default(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.delenv("ORCHESTRATOR_LOCAL_REVISION_WORKFLOW_ENABLED", raising=False)
    monkeypatch.delenv("ORCHESTRATOR_LOCAL_PEER_REVIEW_ENABLED", raising=False)
    monkeypatch.setattr(
        "core.management_bridge.build_core_agent_registry", lambda: object()
    )
    monkeypatch.setattr(
        "core.management_bridge.build_registry_executors",
        lambda registry, request: {
            AgentRole.NEWS: FakeExecutor(AgentRole.NEWS),
            AgentRole.STOCKS: FakeExecutor(AgentRole.STOCKS),
        },
    )
    fake_run = SimpleNamespace(
        success=False,
        peer_review=SimpleNamespace(status="NEEDS_REVISION", revision_requests=()),
        agent_team=None,
        observations=(),
        collaboration_snapshot=lambda: {"revision_workflow": {"draft_status": "NOT_STARTED"}},
    )
    class FakeManager:
        def run(self, request):
            return fake_run
    monkeypatch.setattr(
        "core.management_bridge.ManagementAI",
        lambda *args, **kwargs: FakeManager(),
    )
    monkeypatch.setattr(
        "core.management_bridge.record_collaboration_snapshot",
        lambda **kwargs: None,
    )
    result = run_management_request(
        "u1", "AIニュースと株価を調べて", planner=StaticPlanner()
    )
    assert result == "管理AIの実行で問題が発生したため、同じ専門AIを再実行せずに処理を停止しました。"


def test_opt_in_revision_workflow_uses_bounded_four_identity_evidence(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setenv("ORCHESTRATOR_LOCAL_PEER_REVIEW_ENABLED", "true")
    monkeypatch.setenv("ORCHESTRATOR_LOCAL_PEER_REVIEW_MODEL", "test-local-model")
    monkeypatch.setenv("ORCHESTRATOR_LOCAL_REVISION_WORKFLOW_ENABLED", "true")
    monkeypatch.setenv("ORCHESTRATOR_LOCAL_REVISION_MODEL", "bonsai:9b")
    monkeypatch.setenv("ORCHESTRATOR_LOCAL_REVISION_REVIEW_MODEL", "lfm3:1.7b-qad-q4_0")
    monkeypatch.setattr(
        "core.management_bridge.build_core_agent_registry", lambda: object()
    )
    monkeypatch.setattr(
        "core.management_bridge.build_registry_executors",
        lambda registry, request: {
            AgentRole.NEWS: FakeExecutor(AgentRole.NEWS),
            AgentRole.STOCKS: FakeExecutor(AgentRole.STOCKS),
        },
    )
    target = SimpleNamespace(agent_id="req-1:target", task_ids=("news-task",))
    team = SimpleNamespace(request_id="req-1", agents=(target,))
    revision_request = SimpleNamespace(
        reviewer_id="req-1:original-reviewer",
        target_agent_id=target.agent_id,
        findings=("Add a source citation.",),
    )
    peer_review = SimpleNamespace(
        status="NEEDS_REVISION", revision_requests=(revision_request,)
    )
    fake_run = SimpleNamespace(
        success=False,
        peer_review=peer_review,
        agent_team=team,
        observations=(SimpleNamespace(task_id="news-task", summary="Initial result."),),
        collaboration_snapshot=lambda: {"revision_workflow": {"draft_status": "NOT_STARTED"}},
    )
    class FakeManager:
        def run(self, request):
            return fake_run
    monkeypatch.setattr(
        "core.management_bridge.ManagementAI.with_local_peer_review",
        classmethod(lambda cls, *args, **kwargs: FakeManager()),
    )
    model_instances = []
    class FakeLocalCall:
        def __init__(self, **kwargs):
            self.model = kwargs["model"]
            model_instances.append(self.model)
        def __call__(self, prompt):
            if "Prepare a proposed corrected artifact" in prompt:
                return '{"content":"Revised result with citation.","addressed_findings":["Add a source citation."]}'
            return '{"verdict":"PASS","findings":[]}'
    monkeypatch.setattr(
        "core.local_model_adapter.OllamaLocalModelCall", FakeLocalCall
    )
    captured = {}
    monkeypatch.setattr(
        "core.management_bridge.record_collaboration_snapshot",
        lambda **kwargs: captured.update(kwargs),
    )
    result = run_management_request(
        "u1", "AIニュースと株価を調べて", planner=StaticPlanner()
    )
    assert result == "管理AIの実行で問題が発生したため、同じ専門AIを再実行せずに処理を停止しました。"
    evidence = captured["snapshot"]["revision_workflow"]
    assert evidence["draft_status"] == "PREPARED"
    assert evidence["review_status"] == "PASS"
    assert evidence["execution_authorized"] is False
    assert model_instances == ["bonsai:9b", "lfm3:1.7b-qad-q4_0"]
    assert evidence["independent_reviewer_id"] not in {
        evidence["revision_agent_id"],
        evidence["target_agent_id"],
        evidence["original_reviewer_id"],
    }



def test_revision_workflow_rejects_same_model_for_draft_and_independent_review(monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_LOCAL_PEER_REVIEW_ENABLED", "true")
    monkeypatch.setenv("ORCHESTRATOR_LOCAL_PEER_REVIEW_MODEL", "lfm3:1.7b-qad-q4_0")
    monkeypatch.setenv("ORCHESTRATOR_LOCAL_REVISION_WORKFLOW_ENABLED", "true")
    monkeypatch.setenv("ORCHESTRATOR_LOCAL_REVISION_MODEL", "bonsai:9b")
    monkeypatch.setenv("ORCHESTRATOR_LOCAL_REVISION_REVIEW_MODEL", "bonsai:9b")
    monkeypatch.setattr(
        "core.management_bridge.build_core_agent_registry", lambda: object()
    )
    monkeypatch.setattr(
        "core.management_bridge.build_registry_executors",
        lambda registry, request: {
            AgentRole.NEWS: FakeExecutor(AgentRole.NEWS),
            AgentRole.STOCKS: FakeExecutor(AgentRole.STOCKS),
        },
    )
    target = type("Agent", (), {"agent_id": "req:target", "task_ids": ("news-task",)})()
    team = type("Team", (), {"request_id": "req", "agents": (target,)})()
    revision_request = type("RevisionRequest", (), {
        "reviewer_id": "req:original-reviewer",
        "target_agent_id": target.agent_id,
        "findings": ("Add a source citation.",),
    })()
    peer_review = type("PeerReview", (), {
        "status": "NEEDS_REVISION",
        "revision_requests": (revision_request,),
    })()
    fake_run = type("Run", (), {
        "success": False,
        "peer_review": peer_review,
        "agent_team": team,
        "observations": (type("Observation", (), {
            "task_id": "news-task", "summary": "Initial result."
        })(),),
        "collaboration_snapshot": lambda self: {},
    })()
    class FakeManager:
        def run(self, request):
            return fake_run
    monkeypatch.setattr(
        "core.management_bridge.ManagementAI.with_local_peer_review",
        classmethod(lambda cls, *args, **kwargs: FakeManager()),
    )
    monkeypatch.setattr(
        "core.management_bridge.record_collaboration_snapshot",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not persist incomplete evidence")),
    )
    result = run_management_request(
        "u1", "AIニュースと株価を調べて", planner=StaticPlanner()
    )
    assert result == "管理AIの実行で問題が発生したため、同じ専門AIを再実行せずに処理を停止しました。"
