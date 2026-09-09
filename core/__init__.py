"""Channel-independent AI Core package."""

from .agents import Agent, AgentRegistry, AgentRequest, AgentResponse
from .gateway import AIGateway, AIRequest, AIResponse
from .channel import handle_channel_request
from .langgraph_adapter import agent_request_from_state, ai_request_from_state, response_text
from .langgraph_runtime import CoreGraphState, agent_node_name, build_core_graph
from .legacy_adapter import LegacyNodeAgent, build_legacy_registry
from .orchestration import ExternalWorkflow, WorkflowResult
from .review import (
    AICompetitionLoop,
    ReviewerRegistry,
    ReviewDecision,
    ReviewFinding,
    ReviewResult,
)
from .router import AgentRouter, RouteResult

__all__ = [
    "Agent",
    "AgentRegistry",
    "AgentRequest",
    "AgentResponse",
    "AgentRouter",
    "RouteResult",
    "AIGateway",
    "AIRequest",
    "AIResponse",
    "handle_channel_request",
    "CoreGraphState",
    "agent_node_name",
    "build_core_graph",
    "LegacyNodeAgent",
    "build_legacy_registry",
    "agent_request_from_state",
    "ai_request_from_state",
    "response_text",
    "ExternalWorkflow",
    "WorkflowResult",
    "AICompetitionLoop",
    "ReviewerRegistry",
    "ReviewDecision",
    "ReviewFinding",
    "ReviewResult",
]
