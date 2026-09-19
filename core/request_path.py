"""Incremental request path from the shared Supervisor into the Core graph."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from core.agents import AgentRequest
from core.langgraph_runtime import CoreGraphState
from graph.core_graph import build_current_core_graph
from graph.core_registry import build_core_agent_registry
from graph.supervisor import supervisor_node
from agents.news.intents import is_ai_news_intent
from agents.stocks.intents import is_stock_intent
from agents.english.intents import is_english_learning_intent
from agents.voice.intents import is_voice_intent
from agents.music.intents import is_music_intent
from agents.video.intents import is_video_intent
from agents.jobs.intents import is_job_seeking_intent
from agents.market.intents import is_market_intent
from e2e_status import StepTimer
from core.distributed_agent_bridge import build_agent_registry
from core.distributed_coordinator import DistributedAgentCoordinator
from core.multi_agent import AgentRole
from core.management_contract import Specialist, specialist_boundary


# Explicit, bounded orchestration rules. Keep this list small and deterministic;
# single-intent requests continue through the normal Supervisor/Core graph.
_MULTI_SPECIALIST_RULES: tuple[tuple[tuple[str, ...], Callable[[str], bool]], ...] = (
    # Keep explicit combinations ordered from most specific to least specific.
    (
        ("ai_news", "stocks", "weather"),
        lambda message: is_ai_news_intent(message) and is_stock_intent(message) and _is_weather_intent(message),
    ),
    (
        ("ai_news", "stocks"),
        lambda message: is_ai_news_intent(message) and is_stock_intent(message),
    ),
    (
        ("ai_news", "weather"),
        lambda message: is_ai_news_intent(message) and _is_weather_intent(message),
    ),
    (
        ("stocks", "weather"),
        lambda message: is_stock_intent(message) and _is_weather_intent(message),
    ),
)

_WEATHER_INTENT_TERMS = (
    "天気",
    "天候",
    "気温",
    "温度",
    "降水確率",
    "雨",
    "雪",
    "weather",
    "temperature",
    "forecast",
)


def _is_weather_intent(message: str) -> bool:
    normalized = (message or "").strip().lower()
    return any(term.lower() in normalized for term in _WEATHER_INTENT_TERMS)
_MAX_SPECIALIST_WORKERS = 4

_SPECIALIST_CAPABILITIES: dict[str, str] = {
    "news": "news_retrieval",
    "stocks": "stock_quotes",
    "english": "english_learning",
    "voice": "text_to_speech",
    "music": "music_planning",
    "video": "video_planning",
    "jobs": "job_search",
    "market": "market_summary",
}


def _validate_specialist_capability(specialist: str) -> None:
    try:
        typed = Specialist(specialist)
    except ValueError as exc:
        raise RuntimeError(f"unknown specialist: {specialist}") from exc
    required = _SPECIALIST_CAPABILITIES.get(specialist)
    if required is None:
        raise RuntimeError(f"missing capability mapping: {specialist}")
    boundary = specialist_boundary(typed)
    if required not in boundary.capabilities:
        raise RuntimeError(
            f"specialist capability not approved: {specialist}:{required}"
        )


def _resolve_multi_specialist_plan(message: str) -> tuple[str, ...] | None:
    """Return a deterministic bounded plan when multiple domain intents are explicit."""
    for specialists, matches in _MULTI_SPECIALIST_RULES:
        if matches(message):
            return specialists

    domain_intents: tuple[tuple[str, Callable[[str], bool]], ...] = (
        ("news", is_ai_news_intent),
        ("stocks", is_stock_intent),
        ("english", is_english_learning_intent),
        ("voice", is_voice_intent),
        ("music", is_music_intent),
        ("video", is_video_intent),
        ("jobs", is_job_seeking_intent),
        ("market", is_market_intent),
    )
    matched = tuple(name for name, matcher in domain_intents if matcher(message))
    if len(matched) >= 2:
        if len(matched) > _MAX_SPECIALIST_WORKERS:
            raise RuntimeError("multi-specialist plan exceeds worker limit")
        return matched
    return None


def _run_multi_specialist_request(
    user_id: str,
    message: str,
    *,
    channel: str,
    metadata: Mapping[str, Any],
    specialists: Sequence[str],
) -> dict[str, Any]:
    """Execute bounded specialists concurrently and preserve each result."""
    registry = build_core_agent_registry()
    for specialist in specialists:
        _validate_specialist_capability(specialist)
    request = AgentRequest(user_id=user_id, message=message, channel=channel, metadata=dict(metadata))
    plan = tuple(specialists)
    if not plan:
        raise RuntimeError("multi-specialist plan is empty")
    if len(plan) > _MAX_SPECIALIST_WORKERS:
        raise RuntimeError("multi-specialist plan exceeds worker limit")

    registry_names = {"jobs": "job_seeking", "market": "global_market"}
    agents = []
    for agent_name in plan:
        registry_name = registry_names.get(agent_name, agent_name)
        agent = registry.get(registry_name)
        if not bool(getattr(agent, "enabled", True)):
            raise RuntimeError(f"required specialist disabled: {agent_name}")
        if not agent.can_handle(request):
            raise RuntimeError(f"required specialist rejected request: {agent_name}")
        agents.append((agent_name, agent))

    def execute(item: tuple[str, Any]) -> tuple[str, dict[str, Any]]:
        agent_name, agent = item
        try:
            response = agent.handle(request)
            return agent_name, {
                "text": response.text,
                "metadata": dict(response.metadata),
                "status": "ok",
            }
        except Exception as exc:
            return agent_name, {
                "text": "",
                "metadata": {"feature": agent_name, "status": "error", "error": str(exc)},
                "status": "error",
            }

    with ThreadPoolExecutor(max_workers=min(len(agents), _MAX_SPECIALIST_WORKERS)) as executor:
        completed = list(executor.map(execute, agents))

    results = dict(completed)
    successful_texts = [results[name]["text"] for name in plan if results[name]["status"] == "ok" and results[name]["text"]]
    failures = [name for name in plan if results[name]["status"] == "error"]
    if not successful_texts:
        raise RuntimeError("all multi-specialists failed: " + ", ".join(failures))

    final_reply = "\n\n".join(successful_texts)
    if failures:
        final_reply += "\n\n一部のAgentを実行できませんでした: " + ", ".join(failures)

    return {
        "user_id": user_id,
        "raw_message": message,
        "channel": channel,
        "metadata": dict(metadata),
        "intent": "multi_specialist",
        "next_agent": "management",
        "route": "management:" + "+".join(plan),
        "agent_results": results,
        "final_reply": final_reply,
        "error": None,
        "specialists": list(plan),
        "parallel": True,
        "max_workers": min(len(agents), _MAX_SPECIALIST_WORKERS),
        "failed_specialists": failures,
    }


def _run_distributed_news_request(
    user_id: str,
    message: str,
    *,
    channel: str,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Route explicit AI NEWS requests through the distributed runtime."""
    _validate_specialist_capability("news")
    registry = build_core_agent_registry()
    executors = build_agent_registry(registry).build()
    coordinator = DistributedAgentCoordinator(executors, max_rounds=1)
    request_id = f"news:{channel}:{user_id}".strip()
    report = coordinator.dispatch(request_id, message)
    if not report.success:
        raise RuntimeError(report.runtime.error or "distributed AI NEWS execution failed")
    completed = report.runtime.completed
    if not completed or completed[0].result.task_id != report.contract.task.task_id:
        raise RuntimeError("distributed AI NEWS result contract mismatch")
    result = completed[0].result
    return {
        "user_id": user_id,
        "raw_message": message,
        "channel": channel,
        "metadata": dict(metadata),
        "intent": "distributed_news",
        "next_agent": "news",
        "route": "distributed:news",
        "agent_results": {
            "news": {
                "text": result.summary,
                "metadata": {"role": AgentRole.NEWS.value, "distributed": True},
                "status": "ok",
            }
        },
        "final_reply": result.summary,
        "error": None,
        "specialists": ["news"],
        "parallel": False,
        "max_workers": 1,
        "failed_specialists": [],
    }



def _run_distributed_stocks_request(
    user_id: str,
    message: str,
    *,
    channel: str,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Route explicit stock requests through the distributed runtime."""
    _validate_specialist_capability("stocks")
    registry = build_core_agent_registry()
    executors = build_agent_registry(registry).build()
    coordinator = DistributedAgentCoordinator(executors, max_rounds=1)
    request_id = f"stocks:{channel}:{user_id}".strip()
    report = coordinator.dispatch(request_id, message)
    if not report.success:
        raise RuntimeError(report.runtime.error or "distributed stock execution failed")
    completed = report.runtime.completed
    if not completed or completed[0].result.task_id != report.contract.task.task_id:
        raise RuntimeError("distributed stock result contract mismatch")
    result = completed[0].result
    return {
        "user_id": user_id,
        "raw_message": message,
        "channel": channel,
        "metadata": dict(metadata),
        "intent": "distributed_stocks",
        "next_agent": "stocks",
        "route": "distributed:stocks",
        "agent_results": {
            "stocks": {
                "text": result.summary,
                "metadata": {"role": AgentRole.STOCKS.value, "distributed": True},
                "status": "ok",
            }
        },
        "final_reply": result.summary,
        "error": None,
        "specialists": ["stocks"],
        "parallel": False,
        "max_workers": 1,
        "failed_specialists": [],
    }


def _run_distributed_english_request(
    user_id: str,
    message: str,
    *,
    channel: str,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Route explicit English-learning requests through the distributed runtime."""
    _validate_specialist_capability("english")
    registry = build_core_agent_registry()
    executors = build_agent_registry(registry).build()
    coordinator = DistributedAgentCoordinator(executors, max_rounds=1)
    request_id = f"english:{channel}:{user_id}".strip()
    report = coordinator.dispatch(request_id, message)
    if not report.success:
        raise RuntimeError(report.runtime.error or "distributed English execution failed")
    completed = report.runtime.completed
    if not completed or completed[0].result.task_id != report.contract.task.task_id:
        raise RuntimeError("distributed English result contract mismatch")
    result = completed[0].result
    return {
        "user_id": user_id, "raw_message": message, "channel": channel,
        "metadata": dict(metadata), "intent": "distributed_english",
        "next_agent": "english", "route": "distributed:english",
        "agent_results": {"english": {"text": result.summary, "metadata": {"role": AgentRole.ENGLISH.value, "distributed": True}, "status": "ok"}},
        "final_reply": result.summary, "error": None, "specialists": ["english"],
        "parallel": False, "max_workers": 1, "failed_specialists": [],
    }


def _run_distributed_voice_request(
    user_id: str,
    message: str,
    *,
    channel: str,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Route explicit voice/speaker requests through the distributed runtime."""
    _validate_specialist_capability("voice")
    registry = build_core_agent_registry()
    executors = build_agent_registry(registry).build()
    coordinator = DistributedAgentCoordinator(executors, max_rounds=1)
    request_id = f"voice:{channel}:{user_id}".strip()
    report = coordinator.dispatch(request_id, message)
    if not report.success:
        raise RuntimeError(report.runtime.error or "distributed voice execution failed")
    completed = report.runtime.completed
    if not completed or completed[0].result.task_id != report.contract.task.task_id:
        raise RuntimeError("distributed voice result contract mismatch")
    result = completed[0].result
    return {
        "user_id": user_id, "raw_message": message, "channel": channel,
        "metadata": dict(metadata), "intent": "distributed_voice",
        "next_agent": "voice", "route": "distributed:voice",
        "agent_results": {"voice": {"text": result.summary, "metadata": {"role": AgentRole.VOICE.value, "distributed": True}, "status": "ok"}},
        "final_reply": result.summary, "error": None, "specialists": ["voice"],
        "parallel": False, "max_workers": 1, "failed_specialists": [],
    }


def _run_distributed_music_request(
    user_id: str,
    message: str,
    *,
    channel: str,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Route explicit music requests through the distributed runtime."""
    _validate_specialist_capability("music")
    registry = build_core_agent_registry()
    executors = build_agent_registry(registry).build()
    coordinator = DistributedAgentCoordinator(executors, max_rounds=1)
    request_id = f"music:{channel}:{user_id}".strip()
    report = coordinator.dispatch(request_id, message)
    if not report.success:
        raise RuntimeError(report.runtime.error or "distributed music execution failed")
    completed = report.runtime.completed
    if not completed or completed[0].result.task_id != report.contract.task.task_id:
        raise RuntimeError("distributed music result contract mismatch")
    result = completed[0].result
    return {
        "user_id": user_id,
        "raw_message": message,
        "channel": channel,
        "metadata": dict(metadata),
        "intent": "distributed_music",
        "next_agent": "music",
        "route": "distributed:music",
        "agent_results": {
            "music": {
                "text": result.summary,
                "metadata": {"role": AgentRole.MUSIC.value, "distributed": True},
                "status": "ok",
            }
        },
        "final_reply": result.summary,
        "error": None,
        "specialists": ["music"],
        "parallel": False,
        "max_workers": 1,
        "failed_specialists": [],
    }


def _run_distributed_video_request(
    user_id: str, message: str, *, channel: str, metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Route explicit video requests through the distributed runtime."""
    _validate_specialist_capability("video")
    registry = build_core_agent_registry()
    executors = build_agent_registry(registry).build()
    report = DistributedAgentCoordinator(executors, max_rounds=1).dispatch(
        f"video:{channel}:{user_id}".strip(), message
    )
    if not report.success:
        raise RuntimeError(report.runtime.error or "distributed video execution failed")
    completed = report.runtime.completed
    if not completed or completed[0].result.task_id != report.contract.task.task_id:
        raise RuntimeError("distributed video result contract mismatch")
    result = completed[0].result
    return {
        "user_id": user_id, "raw_message": message, "channel": channel,
        "metadata": dict(metadata), "intent": "distributed_video",
        "next_agent": "video", "route": "distributed:video",
        "agent_results": {"video": {"text": result.summary,
            "metadata": {"role": AgentRole.VIDEO.value, "distributed": True}, "status": "ok"}},
        "final_reply": result.summary, "error": None, "specialists": ["video"],
        "parallel": False, "max_workers": 1, "failed_specialists": [],
    }



def _run_distributed_jobs_request(
    user_id: str, message: str, *, channel: str, metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Route explicit job-seeking requests through the distributed runtime."""
    _validate_specialist_capability("jobs")
    registry = build_core_agent_registry()
    executors = build_agent_registry(registry).build()
    report = DistributedAgentCoordinator(executors, max_rounds=1).dispatch(
        f"jobs:{channel}:{user_id}".strip(), message
    )
    if not report.success:
        raise RuntimeError(report.runtime.error or "distributed jobs execution failed")
    completed = report.runtime.completed
    if not completed or completed[0].result.task_id != report.contract.task.task_id:
        raise RuntimeError("distributed jobs result contract mismatch")
    result = completed[0].result
    return {
        "user_id": user_id, "raw_message": message, "channel": channel,
        "metadata": dict(metadata), "intent": "distributed_jobs",
        "next_agent": "jobs", "route": "distributed:jobs",
        "agent_results": {"jobs": {"text": result.summary,
            "metadata": {"role": AgentRole.JOBS.value, "distributed": True}, "status": "ok"}},
        "final_reply": result.summary, "error": None, "specialists": ["jobs"],
        "parallel": False, "max_workers": 1, "failed_specialists": [],
    }



def _run_distributed_market_request(
    user_id: str, message: str, *, channel: str, metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Route explicit market requests through the distributed runtime."""
    _validate_specialist_capability("market")
    registry = build_core_agent_registry()
    executors = build_agent_registry(registry).build()
    report = DistributedAgentCoordinator(executors, max_rounds=1).dispatch(
        f"market:{channel}:{user_id}".strip(), message
    )
    if not report.success:
        raise RuntimeError(report.runtime.error or "distributed market execution failed")
    completed = report.runtime.completed
    if not completed or completed[0].result.task_id != report.contract.task.task_id:
        raise RuntimeError("distributed market result contract mismatch")
    result = completed[0].result
    return {
        "user_id": user_id, "raw_message": message, "channel": channel,
        "metadata": dict(metadata), "intent": "distributed_market",
        "next_agent": "market", "route": "distributed:market",
        "agent_results": {"market": {"text": result.summary,
            "metadata": {"role": AgentRole.MARKET.value, "distributed": True}, "status": "ok"}},
        "final_reply": result.summary, "error": None, "specialists": ["market"],
        "parallel": False, "max_workers": 1, "failed_specialists": [],
    }


def run_core_request(
    user_id: str,
    message: str,
    *,
    channel: str = "unknown",
    metadata: Mapping[str, Any] | None = None,
    call_mcp_tool=None,
) -> dict[str, Any]:
    """Classify with Supervisor, then execute one or a bounded specialist plan via Core."""
    request_metadata = dict(metadata or {})
    specialists = _resolve_multi_specialist_plan(message)
    if specialists is not None:
        with StepTimer("core") as core_timer:
            try:
                result = _run_multi_specialist_request(
                    user_id,
                    message,
                    channel=channel,
                    metadata=request_metadata,
                    specialists=specialists,
                )
            except Exception as exc:
                core_timer.fail(error=exc, error_location="core/request_path.multi_specialist")
                raise
            core_timer.ok()
            return result

    if is_ai_news_intent(message):
        with StepTimer("core") as core_timer:
            try:
                result = _run_distributed_news_request(
                    user_id,
                    message,
                    channel=channel,
                    metadata=request_metadata,
                )
            except Exception as exc:
                core_timer.fail(error=exc, error_location="core/request_path.distributed_news")
                raise
            core_timer.ok()
            return result

    if is_stock_intent(message):
        with StepTimer("core") as core_timer:
            try:
                result = _run_distributed_stocks_request(
                    user_id,
                    message,
                    channel=channel,
                    metadata=request_metadata,
                )
            except Exception as exc:
                core_timer.fail(error=exc, error_location="core/request_path.distributed_stocks")
                raise
            core_timer.ok()
            return result

    if is_english_learning_intent(message):
        with StepTimer("core") as core_timer:
            try:
                result = _run_distributed_english_request(user_id, message, channel=channel, metadata=request_metadata)
            except Exception as exc:
                core_timer.fail(error=exc, error_location="core/request_path.distributed_english")
                raise
            core_timer.ok()
            return result

    if is_market_intent(message):
        with StepTimer("core") as core_timer:
            try:
                result = _run_distributed_market_request(user_id, message, channel=channel, metadata=request_metadata)
            except Exception as exc:
                core_timer.fail(error=exc, error_location="core/request_path.distributed_market")
                raise
            core_timer.ok()
            return result

    if is_job_seeking_intent(message):
        with StepTimer("core") as core_timer:
            try:
                result = _run_distributed_jobs_request(user_id, message, channel=channel, metadata=request_metadata)
            except Exception as exc:
                core_timer.fail(error=exc, error_location="core/request_path.distributed_jobs")
                raise
            core_timer.ok()
            return result

    if is_video_intent(message):
        with StepTimer("core") as core_timer:
            try:
                result = _run_distributed_video_request(user_id, message, channel=channel, metadata=request_metadata)
            except Exception as exc:
                core_timer.fail(error=exc, error_location="core/request_path.distributed_video")
                raise
            core_timer.ok()
            return result

    if is_music_intent(message):
        with StepTimer("core") as core_timer:
            try:
                result = _run_distributed_music_request(
                    user_id, message, channel=channel, metadata=request_metadata
                )
            except Exception as exc:
                core_timer.fail(error=exc, error_location="core/request_path.distributed_music")
                raise
            core_timer.ok()
            return result

    if is_voice_intent(message):
        with StepTimer("core") as core_timer:
            try:
                result = _run_distributed_voice_request(user_id, message, channel=channel, metadata=request_metadata)
            except Exception as exc:
                core_timer.fail(error=exc, error_location="core/request_path.distributed_voice")
                raise
            core_timer.ok()
            return result

    initial: CoreGraphState = {
        "user_id": user_id,
        "raw_message": message,
        "channel": channel,
        "metadata": request_metadata,
        "agent_results": {},
    }
    if call_mcp_tool is not None:
        initial["call_mcp_tool"] = call_mcp_tool  # type: ignore[typeddict-item]

    with StepTimer("core") as core_timer:
        try:
            classified = supervisor_node(initial)  # type: ignore[arg-type]
        except Exception as exc:
            core_timer.fail(error=exc, error_location="core/request_path.supervisor")
            raise

        with StepTimer("agent") as agent_timer:
            try:
                result = dict(build_current_core_graph().invoke(classified))
            except Exception as exc:
                agent_timer.fail(error=exc, error_location="core/request_path.agent")
                core_timer.fail(error=exc, error_location="core/request_path.agent")
                raise

        agent_timer.ok()
        core_timer.ok()
        return result


def extract_core_reply(result: Mapping[str, Any]) -> str:
    """Return the Core final reply as text."""
    value = result.get("final_reply")
    if isinstance(value, str):
        return value
    return "Agent結果なし"
