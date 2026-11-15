"""Safe production bridge for multi-specialist requests.

Single-specialist requests keep their existing direct routing. Only requests that
match two or more supported read/query specialist domains are delegated through
Management AI, so this layer can be introduced without changing the existing
single-agent path.
"""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import os
from typing import Sequence

from agents.stocks.node import StocksAgent

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
from core.collaboration_audit import record_collaboration_snapshot
from core.revision_workflow import run_revision_workflow_if_needed
from core.management_ai import (
    ManagementAI,
    ManagementPlan,
    ManagementPlanner,
    ManagementPlanningError,
    ModelManagementPlanner,
)
from core.management_contract import ManagementDecision, ManagementRequest
from core.multi_agent import AgentRole, AgentTask
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


def _source_bound_instruction(role: AgentRole, message: str) -> str | None:
    """Return a deterministic read/query instruction bound to the user source.

    Management-AI model prose is not trusted to invent search queries or ticker
    symbols. For external-data specialists, the bridge derives a minimal
    canonical instruction locally.
    """
    if role is AgentRole.NEWS:
        return "AI NEWS"

    if role is AgentRole.STOCKS:
        resolved = StocksAgent._resolve_ticker(str(message or ""))
        if resolved is None:
            return None
        ticker, _display_name = resolved
        return f"ticker {ticker}"

    return None


def _bind_source_instructions(plan: ManagementPlan, message: str) -> ManagementPlan:
    """Replace model-generated data-source instructions with source-bound ones."""
    tasks = tuple(
        replace(task, instruction=bound)
        if (bound := _source_bound_instruction(task.role, message)) is not None
        else task
        for task in plan.tasks
    )
    if tasks == plan.tasks:
        return plan
    return replace(plan, tasks=tasks)


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
        try:
            plan = self._planner.plan(request, decision, feedback)
        except ManagementPlanningError:
            raise
        except Exception as exc:
            raise ManagementPlanningError(
                "management planner failed"
            ) from exc
        unexpected_tasks = tuple(
            task for task in plan.tasks if task.role not in self._allowed_roles
        )
        unexpected_task_ids = {task.task_id for task in unexpected_tasks}
        filtered_tasks = tuple(
            task
            for task in plan.tasks
            if task.role in self._allowed_roles
            and not any(dependency in unexpected_task_ids for dependency in task.depends_on)
        )
        planned_roles = {task.role for task in filtered_tasks}
        missing_roles = sorted(
            (role for role in self._allowed_roles if role not in planned_roles),
            key=lambda role: role.value,
        )
        if missing_roles:
            # The model may invent a dependency on an out-of-scope role. Never
            # execute that graph and never let the model widen the allowed set.
            # Replace the affected/missing roles with bounded, dependency-free
            # tasks derived only from the deterministic role set detected from
            # the user's message.
            fallback_tasks = list(filtered_tasks)
            used_ids = {task.task_id for task in fallback_tasks}
            for role in missing_roles:
                base_id = f"{role.value}-task"
                task_id = base_id
                suffix = 2
                while task_id in used_ids:
                    task_id = f"{base_id}-{suffix}"
                    suffix += 1
                fallback_tasks.append(
                    AgentTask(
                        task_id=task_id,
                        role=role,
                        instruction=f"Handle the user's request for the {role.value} specialist.",
                        resources=frozenset({role.value}),
                        priority=1,
                    )
                )
                used_ids.add(task_id)
            plan = replace(
                plan,
                tasks=tuple(fallback_tasks),
                parallel_safe=False,
            )
        elif unexpected_tasks:
            plan = replace(plan, tasks=filtered_tasks)
        return _bind_source_instructions(plan, request.message)


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
    local_review_enabled = os.environ.get(
        "ORCHESTRATOR_LOCAL_PEER_REVIEW_ENABLED", ""
    ).strip().lower() in {"1", "true", "yes", "on"}
    if local_review_enabled:
        local_model = os.environ.get("ORCHESTRATOR_LOCAL_PEER_REVIEW_MODEL", "").strip()
        if not local_model:
            print("[MANAGEMENT AI] local peer review enabled without a model; fail closed")
            return _MANAGEMENT_EXECUTION_FAILURE
        manager = ManagementAI.with_local_peer_review(
            executors,
            model=local_model,
            base_url=os.environ.get(
                "ORCHESTRATOR_LOCAL_PEER_REVIEW_URL",
                "http://127.0.0.1:11434/v1",
            ),
            planner=restricted_planner,
            max_workers=1,
            isolated=False,
        )
    else:
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

    snapshot = run.collaboration_snapshot()
    revision_enabled = os.environ.get(
        "ORCHESTRATOR_LOCAL_REVISION_WORKFLOW_ENABLED", ""
    ).strip().lower() in {"1", "true", "yes", "on"}
    if revision_enabled:
        # Revision drafting is separately opt-in and only follows a verified
        # NEEDS_REVISION result from the local peer-review stage.
        if not local_review_enabled or run.peer_review is None:
            print("[MANAGEMENT AI] revision workflow requires local peer review; fail closed")
            return _MANAGEMENT_EXECUTION_FAILURE
        if run.peer_review.status == "NEEDS_REVISION":
            if not run.agent_team or not run.peer_review.revision_requests:
                print("[MANAGEMENT AI] revision evidence is incomplete; fail closed")
                return _MANAGEMENT_EXECUTION_FAILURE
            revision_request = run.peer_review.revision_requests[0]
            target = next(
                (agent for agent in run.agent_team.agents
                 if agent.agent_id == revision_request.target_agent_id),
                None,
            )
            observation = next(
                (item for item in run.observations
                 if target is not None and item.task_id in target.task_ids),
                None,
            )
            if target is None or observation is None:
                print("[MANAGEMENT AI] revision target evidence is missing; fail closed")
                return _MANAGEMENT_EXECUTION_FAILURE
            request_id = run.agent_team.request_id
            revision_agent_id = f"{request_id}:revision:{sha256(target.agent_id.encode()).hexdigest()[:12]}"
            independent_reviewer_id = f"{request_id}:revision-review:{sha256((target.agent_id + revision_request.reviewer_id).encode()).hexdigest()[:12]}"
            try:
                from core.local_model_adapter import OllamaLocalModelCall
                revision_model = os.environ.get(
                    "ORCHESTRATOR_LOCAL_REVISION_MODEL",
                    os.environ.get("ORCHESTRATOR_LOCAL_PEER_REVIEW_MODEL", ""),
                ).strip()
                if not revision_model:
                    raise ValueError("local revision model is not configured")
                model_call = OllamaLocalModelCall(
                    model=revision_model,
                    base_url=os.environ.get(
                        "ORCHESTRATOR_LOCAL_REVISION_URL",
                        os.environ.get(
                            "ORCHESTRATOR_LOCAL_PEER_REVIEW_URL",
                            "http://127.0.0.1:11434/v1",
                        ),
                    ),
                )
                snapshot["revision_workflow"] = run_revision_workflow_if_needed(
                    original_verdict="NEEDS_REVISION",
                    request_id=request_id,
                    task_id=observation.task_id,
                    revision_agent_id=revision_agent_id,
                    target_agent_id=target.agent_id,
                    original_reviewer_id=revision_request.reviewer_id,
                    independent_reviewer_id=independent_reviewer_id,
                    original_result=observation.summary,
                    findings=revision_request.findings,
                    draft_model_call=model_call,
                    review_model_call=model_call,
                )
                # This is one local model adapter called twice under distinct
                # logical identities, NOT proof of independent model processes.
            except Exception as exc:
                print(f"[MANAGEMENT AI] revision workflow failed closed: {type(exc).__name__}")
                return _MANAGEMENT_EXECUTION_FAILURE
    try:
        record_collaboration_snapshot(
            user_id=request.user_id,
            snapshot=snapshot,
        )
    except Exception as exc:
        # Observability must never change task execution or trigger a retry.
        print(f"[MANAGEMENT AI] collaboration audit unavailable: {type(exc).__name__}")

    if not run.success:
        print("[MANAGEMENT AI] distributed round reported failure; no legacy retry")
        return _MANAGEMENT_EXECUTION_FAILURE

    parts: list[str] = []
    for observation in run.observations:
        label = _ROLE_LABELS.get(observation.role, observation.role.value)
        parts.append("【" + label + "】\n" + observation.summary)

    return "\n\n".join(parts) if parts else None

__all__ = [
    "SUPPORTED_MULTI_SPECIALISTS",
    "run_management_request",
    "should_route_to_management_ai",
    "specialist_roles_for_message",
]
