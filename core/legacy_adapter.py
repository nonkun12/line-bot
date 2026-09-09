"""Adapters for migrating existing LangGraph nodes into the Core Agent contract."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .agents import Agent, AgentRegistry, AgentRequest, AgentResponse


@dataclass
class LegacyNodeAgent:
    """Expose a legacy state->state node through the channel-independent Agent API."""

    name: str
    node: Callable[[Mapping[str, Any]], Mapping[str, Any]]
    description: str = "Legacy LangGraph node adapter"
    priority: int = 0
    enabled: bool = True
    graph_node: str | None = None
    route_key: str | None = None
    extra_state: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("agent name is required")
        if not callable(self.node):
            raise TypeError("node must be callable")
        if self.graph_node is not None and (
            not isinstance(self.graph_node, str) or not self.graph_node.strip()
        ):
            raise ValueError("graph_node must be a non-empty string or None")
        if self.route_key is None:
            self.route_key = self.name

    def can_handle(self, request: AgentRequest) -> bool:
        return request.metadata.get("next_agent") == self.route_key

    def handle(self, request: AgentRequest) -> AgentResponse:
        state: dict[str, Any] = {
            "user_id": request.user_id,
            "raw_message": request.message,
            **dict(request.metadata),
            **dict(self.extra_state),
        }
        result = self.node(state)
        if not isinstance(result, Mapping):
            raise TypeError("legacy node must return a mapping")

        results = result.get("agent_results", {})
        if isinstance(results, Mapping):
            item = results.get(self.name, {})
            if isinstance(item, Mapping):
                text = item.get("text")
                if isinstance(text, str):
                    return AgentResponse(
                        text=text,
                        metadata={k: v for k, v in item.items() if k != "text"},
                    )

        final_reply = result.get("final_reply")
        if isinstance(final_reply, str):
            return AgentResponse(text=final_reply)
        return AgentResponse(text="")


def build_legacy_registry(
    nodes: Mapping[str, Callable[[Mapping[str, Any]], Mapping[str, Any]]],
    *,
    graph_nodes: Mapping[str, str] | None = None,
    priorities: Mapping[str, int] | None = None,
) -> AgentRegistry:
    """Create a Core registry from legacy route-key -> LangGraph-node functions."""
    graph_nodes = graph_nodes or {}
    priorities = priorities or {}
    agents: list[Agent] = []
    for name, node in nodes.items():
        agents.append(
            LegacyNodeAgent(
                name=name,
                node=node,
                graph_node=graph_nodes.get(name),
                priority=priorities.get(name, 0),
            )
        )
    return AgentRegistry(agents)
