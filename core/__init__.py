"""Channel-independent AI Core package."""

from .agents import Agent, AgentRegistry, AgentRequest, AgentResponse
from .gateway import AIGateway, AIRequest, AIResponse
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
    "AICompetitionLoop",
    "ReviewerRegistry",
    "ReviewDecision",
    "ReviewFinding",
    "ReviewResult",
]
