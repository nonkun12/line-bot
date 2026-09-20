"""Safe production bridge for multi-specialist requests.

Single-specialist requests keep their existing direct routing. Only requests that
match two or more supported read/query specialist domains are delegated through
Management AI, so this layer can be introduced without changing the existing
single-agent path.
"""
from __future__ import annotations

from typing import Sequence

from agents.english.intents import is_english_learning_intent
from agents.news.intents import is_ai_news_intent
from agents.stocks.intents import is_stock_intent
from agents.market.intents import is_market_intent
from agents.voice.intents import is_voice_intent
from agents.jobs.intents import is_job_seeking_intent
from agents.music.intents import is_music_intent
from agents.video.intents import is_video_intent
from core.agents import AgentRequest
from core.distributed_scheduler import DistributedExecutionError
from core.management_ai import (
    ManagementAI,
    ManagementPlan,
    ManagementPlanner,
    ManagementPlanningError,
    ModelManagementPlanner,
)
from core.management_contract import ManagementDecision, ManagementRequest
from core.multi_agent import AgentRole
from core.specialist_executor import build_registry_executors
from core.specialist_gate import SpecialistGateError, assert_all_approved
from graph.core_registry import build_core_agent_registry


SUPPORTED_MULTI_SPECIALISTS = frozenset(
    {
        AgentRole.ENGLISH,
        AgentRole.NEWS,
        AgentRole.STOCKS,
        AgentRole.MARKET,
        AgentRole.VOICE,
        AgentRole.JOBS,
        AgentRole.MUSIC,
        AgentRole.VIDEO,
    }
)

_MANAGEMENT_EXECUTION_FAILURE = (
    "管理AIの実行で問題が発生したため、同じ専門AIを再実行せずに処理を停止しました。"
)

_ROLE_LABELS = {
    AgentRole.ENGLISH: "English",
    AgentRole.NEWS: "AI NEWS",
    AgentRole.STOCKS: "Stocks",
    AgentRole.MARKET: "Market AI",
    AgentRole.VOICE: "Voice",
    AgentRole.JOBS: "Jobs",
    AgentRole.MUSIC: "Music",
    AgentRole.VIDEO: "Video",
}


def specialist_roles_for_message(message: str) -> frozenset[AgentRole]:
    text = str(message or "").strip()
    roles: set[AgentRole] = set()
    if is_english_learning_intent(text):
        roles.add(AgentRole.ENGLISH)
    if is_ai_news_intent(text):
        roles.add(AgentRole.NEWS)
    market_intent = is_market_intent(text)
    if market_intent:
        roles.add(AgentRole.MARKET)
    broad_market_only = any(
        term in text.casefold()
        for term in ("世界株価", "世界の株価", "世界の市場")
    )
    if is_stock_intent(text) and not broad_market_only:
        roles.add(AgentRole.STOCKS)
    if is_voice_intent(text):
        roles.add(AgentRole.VOICE)
    if is_job_seeking_intent(text):
        roles.add(AgentRole.JOBS)
    if is_music_intent(text):
        roles.add(AgentRole.MUSIC)
    if is_video_intent(text):
        roles.add(AgentRole.VIDEO)
    return frozenset(roles)


def should_route_to_management_ai(message: str) -> bool:
    """Use Management AI only when at least two supported specialists match."""
    return len(specialist_roles_for_message(message)) >= 2


class _CandidateRestrictedPlanner(ManagementPlanner):
    """Keep model planning inside the domains detected from the user request."""

    def __init__(self, planner: ManagementPlanner, allowed_roles: frozenset[AgentRole]) -> None:
        self._planner = planner
        self._allowed_roles = allowed_roles

    def plan(
        self,
        request: ManagementRequest,
        decision: ManagementDecision,
        feedback: Sequence[str] = (),
    ) -> ManagementPlan:
        plan = self._planner.plan(request, decision, feedback)
        planned_roles = {task.role for task in plan.tasks}
        unexpected = sorted(
            {task.role.value for task in plan.tasks if task.role not in self._allowed_roles}
        )
        missing = sorted(role.value for role in self._allowed_roles if role not in planned_roles)
        if unexpected:
            raise ManagementPlanningError(
                "management plan requested an undetected specialist role: "
                + ", ".join(unexpected)
            )
        if missing:
            raise ManagementPlanningError(
                "management plan omitted detected specialist role: "
                + ", ".join(missing)
            )
        return plan


def run_management_request(
    user_id: str,
    message: str,
    *,
    channel: str = "unknown",
    metadata: dict | None = None,
    planner: ManagementPlanner | None = None,
) -> str | None:
    """Run one bounded Management-AI round and return a combined specialist reply.

    Returns None when the request is not eligible or the new orchestration path
    fails validation/execution; callers can then preserve the legacy route.
    """
    allowed_roles = specialist_roles_for_message(message)
    if len(allowed_roles) < 2:
        return None

    # Capability gate BEFORE any registry/planner (model) call. A denial is a
    # policy decision, not a transient failure: it is raised, never turned into
    # ``None``, so the caller cannot silently fall back to another route.
    assert_all_approved(allowed_roles)

    request = AgentRequest(
        user_id=str(user_id),
        message=str(message),
        channel=str(channel),
        metadata=dict(metadata or {}),
    )
    management_request = ManagementRequest(
        request.user_id,
        request.message,
        channel=request.channel,
        metadata=request.metadata,
    )
    registry = build_core_agent_registry()
    executors = build_registry_executors(registry, request)
    if not executors:
        return None

    restricted_planner = _CandidateRestrictedPlanner(
        planner or ModelManagementPlanner(),
        allowed_roles,
    )
    manager = ManagementAI(
        executors,
        planner=restricted_planner,
        max_workers=1,
        isolated=False,
    )

    try:
        run = manager.run(management_request)
    except SpecialistGateError:
        raise  # fail-closed: never fall back to the legacy route on a gate denial
    except ManagementPlanningError as exc:
        # Planning failed before specialist execution; preserving the legacy route
        # is safe because no distributed specialist has run yet.
        print(f"[MANAGEMENT AI] planner failed; fallback to legacy route: {type(exc).__name__}: {exc}")
        return None
    except DistributedExecutionError as exc:
        # An executor may already have produced side effects before failing.
        # Never retry the request through the legacy route.
        print(f"[MANAGEMENT AI] distributed execution failed; no legacy retry: {type(exc).__name__}: {exc}")
        return _MANAGEMENT_EXECUTION_FAILURE
    except Exception as exc:
        # Treat unexpected Management AI failures conservatively. A retry could
        # duplicate external effects from a partially executed round.
        print(f"[MANAGEMENT AI] unexpected execution failure; no legacy retry: {type(exc).__name__}: {exc}")
        return _MANAGEMENT_EXECUTION_FAILURE

    if not run.success:
        print("[MANAGEMENT AI] distributed round reported failure; no legacy retry")
        return _MANAGEMENT_EXECUTION_FAILURE

    task_map = {task.task_id: task for task in run.plan.tasks}
    parts: list[str] = []
    for result in run.distributed.results:
        task = task_map.get(result.task_id)
        if task is None or not result.summary.strip():
            continue
        label = _ROLE_LABELS.get(task.role, task.role.value)
        parts.append("【" + label + "】\n" + result.summary.strip())

    return "\n\n".join(parts) if parts else None

__all__ = [
    "SUPPORTED_MULTI_SPECIALISTS",
    "run_management_request",
    "should_route_to_management_ai",
    "specialist_roles_for_message",
]
