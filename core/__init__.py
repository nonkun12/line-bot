"""Channel-independent AI Core package."""

from .agents import Agent, AgentRegistry, AgentRequest, AgentResponse
from .gateway import AIGateway, AIRequest, AIResponse
from .langgraph_adapter import agent_request_from_state, ai_request_from_state, response_text
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
    "agent_request_from_state",
    "ai_request_from_state",
    "response_text",
    "AICompetitionLoop",
    "ReviewerRegistry",
    "ReviewDecision",
    "ReviewFinding",
    "ReviewResult",
]
