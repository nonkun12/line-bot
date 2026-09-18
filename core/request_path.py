""""Incremental request path from the shared Supervisor into the Core graph."""

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
from e2e_status import StepTimer


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


def _resolve_multi_specialist_plan(message: str) -> tuple[str, ...] | None:
    """Return a deterministic multi-agent plan when multiple intents are explicit."""
    for specialists, matches in _MULTI_SPECIALIST_RULES:
        if matches(message):
            return specialists
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
    request = AgentRequest(user_id=user_id, message=message, channel=channel, metadata=dict(metadata))
    plan = tuple(specialists)
    if not plan:
        raise RuntimeError("multi-specialist plan is empty")
    if len(plan) > _MAX_SPECIALIST_WORKERS:
        raise RuntimeError("multi-specialist plan exceeds worker limit")

    agents = []
    for agent_name in plan:
        agent = registry.get(agent_name)
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
"