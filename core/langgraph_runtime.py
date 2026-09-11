"""Core-native LangGraph runtime with dynamically registered agents."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from .agents import Agent, AgentRegistry, AgentResponse
from .langgraph_adapter import agent_request_from_state


class CoreGraphState(TypedDict, total=False):
    """Minimal state contract shared by dynamically registered Core agents."""

    user_id: str
    raw_message: str
    channel: str
    request_id: str
    intent: str | None
    next_agent: str | None
    route: str | None
    call_mcp_tool: Any
    agent_results: dict[str, Any]
    final_reply: str | None
    error: str | None


def agent_node_name(name: str) -> str:
    """Return a collision-resistant LangGraph node name for an arbitrary agent name."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("agent name is required")
    encoded = name.encode("utf-8").hex()
    return f"core_agent__{encoded}"


def _normalize_response(result: AgentResponse | str) -> AgentResponse:
    if isinstance(result, AgentResponse):
        return result
    if isinstance(result, str):
        return AgentResponse(text=result)
    raise TypeError("agent must return AgentResponse or str")


def _make_agent_node(name: str, agent: Agent):
    def node(state: CoreGraphState) -> CoreGraphState:
        request = agent_request_from_state(state)
        response = _normalize_response(agent.handle(request))
        results = dict(state.get("agent_results", {}))
        results[name] = {
            "text": response.text,
            "metadata": dict(response.metadata),
        }
        return {
            **state,
            "agent_results": results,
            "final_reply": response.text,
            "next_agent": name,
            "error": None,
        }

    node.__name__ = f"core_agent_{name}"
    return node


def build_core_graph(
    registry: AgentRegistry,
    *,
    fallback_text: str = "対応できるAgentが登録されていません。",
):
    """Build a standalone LangGraph whose executable agent nodes come from the registry."""
    if not isinstance(registry, AgentRegistry):
        raise TypeError("registry must be an AgentRegistry")
    if not isinstance(fallback_text, str):
        raise TypeError("fallback_text must be a string")

    builder = StateGraph(CoreGraphState)

    def resolve_route(state: CoreGraphState) -> str:
        next_agent = state.get("next_agent")
        if isinstance(next_agent, str) and next_agent.strip():
            try:
                selected = registry.get(next_agent)
            except KeyError:
                selected = None
            if selected is not None and bool(getattr(selected, "enabled", True)):
                return agent_node_name(selected.name)

        agent = registry.resolve(agent_request_from_state(state))
        if agent is not None:
            return agent_node_name(agent.name)
        return "core_fallback"

    def core_router(state: CoreGraphState) -> CoreGraphState:
        return {**state, "route": resolve_route(state)}

    def core_fallback(state: CoreGraphState) -> CoreGraphState:
        return {
            **state,
            "final_reply": fallback_text,
            "error": None,
        }

    def core_finalizer(state: CoreGraphState) -> CoreGraphState:
        return state

    builder.add_node("core_router", core_router)
    for name in registry.names():
        builder.add_node(agent_node_name(name), _make_agent_node(name, registry.get(name)))
    builder.add_node("core_fallback", core_fallback)
    builder.add_node("core_finalizer", core_finalizer)

    builder.add_edge(START, "core_router")
    builder.add_conditional_edges(
        "core_router",
        lambda state: state.get("route", "core_fallback"),
    )

    for name in registry.names():
        builder.add_edge(agent_node_name(name), "core_finalizer")
    builder.add_edge("core_fallback", "core_finalizer")
    builder.add_edge("core_finalizer", END)

    return builder.compile()
