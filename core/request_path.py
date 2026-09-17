"""Incremental request path from the shared Supervisor into the Core graph."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.agents import AgentRequest
from core.langgraph_runtime import CoreGraphState
from graph.core_graph import build_current_core_graph
from graph.core_registry import build_core_agent_registry
from graph.supervisor import supervisor_node
from agents.news.intents import is_ai_news_intent
from agents.stocks.intents import is_stock_intent
from e2e_status import StepTimer


def _is_combined_news_stock_request(message: str) -> bool:
    """Detect requests that explicitly require both NEWS and stock results."""
    return is_ai_news_intent(message) and is_stock_intent(message)


def _run_combined_news_stock_request(
    user_id: str,
    message: str,
    *,
    channel: str,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Run both specialist agents and preserve both outputs for final formatting.

    The normal Core graph selects a single next_agent. That is correct for
    single-intent requests, but it silently drops the second specialist when a
    user asks for AI NEWS plus a stock quote in one LINE message. This bounded
    path makes the multi-specialist requirement explicit and keeps each agent's
    result independently inspectable.
    """
    registry = build_core_agent_registry()
    request = AgentRequest(
        user_id=user_id,
        message=message,
        channel=channel,
        metadata=dict(metadata),
    )

    results: dict[str, dict[str, Any]] = {}
    texts: list[str] = []

    for agent_name in ("ai_news", "stocks"):
        agent = registry.get(agent_name)
        if not bool(getattr(agent, "enabled", True)):
            raise RuntimeError(f"required specialist disabled: {agent_name}")
        if not agent.can_handle(request):
            raise RuntimeError(f"required specialist rejected request: {agent_name}")

        response = agent.handle(request)
        results[agent_name] = {
            "text": response.text,
            "metadata": dict(response.metadata),
        }
        texts.append(response.text)

    final_reply = "\n\n".join(texts)
    return {
        "user_id": user_id,
        "raw_message": message,
        "channel": channel,
        "metadata": dict(metadata),
        "intent": "multi_specialist",
        "next_agent": "management",
        "route": "management:ai_news+stocks",
        "agent_results": results,
        "final_reply": final_reply,
        "error": None,
        "specialists": ["ai_news", "stocks"],
    }


def run_core_request(
    user_id: str,
    message: str,
    *,
    channel: str = "unknown",
    metadata: Mapping[str, Any] | None = None,
    call_mcp_tool=None,
) -> dict[str, Any]:
    """Classify with the existing Supervisor, then execute the selected agent via Core."""
    request_metadata = dict(metadata or {})

    # A combined request must not be reduced to the first matching intent.
    # This is the regression fix for "AI NEWS + stock" where the stock result
    # previously disappeared from the final LINE response.
    if _is_combined_news_stock_request(message):
        with StepTimer("core") as core_timer:
            try:
                result = _run_combined_news_stock_request(
                    user_id,
                    message,
                    channel=channel,
                    metadata=request_metadata,
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

    # LINE input ownership belongs to the actual webhook boundary in config.py.
    # Core/Agent execution must not record line_in again, otherwise one request
    # produces two input events and can move the E2E cycle timestamp forward.
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
