"""Incremental request path from the shared Supervisor into the Core graph."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
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
_MULTI_SPECIALIST_RULES: tuple[tuple[tuple[str, ...], Any], ...] = (
    (("ai_news", "stocks"), lambda message: is_ai_news_intent(message) and is_stock_intent(message)),
)


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
    """Execute a bounded specialist plan and preserve every result."""
    registry = build_core_agent_registry()
    request = AgentRequest(user_id=user_id, message=message, channel=channel, metadata=dict(metadata))
    results: dict[str, dict[str, Any]] = {}
    texts: list[str] = []

    for agent_name in specialists:
        agent = registry.get(agent_name)
        if not bool(getattr(agent, "enabled", True)):
            raise RuntimeError(f"required specialist disabled: {agent_name}")
        if not agent.can_handle(request):
            raise RuntimeError(f"required specialist rejected request: {agent_name}")
        response = agent.handle(request)
        results[agent_name] = {"text": response.text, "metadata": dict(response.metadata)}
        texts.append(response.text)

    return {
        "user_id": user_id,
        "raw_message": message,
        "channel": channel,
        "metadata": dict(metadata),
        "intent": "multi_specialist",
        "next_agent": "management",
        "route": "management:" + "+".join(specialists),
        "agent_results": results,
        "final_reply": "\n\n".join(texts),
        "error": None,
        "specialists": list(specialists),
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