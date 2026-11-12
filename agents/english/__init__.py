"""Public English-learning agent exports.

The package-level ``agent`` keeps the historical ``english`` contract.
The richer follow-up implementation remains available from ``agents.english.node``.
"""

from agents.english_agent import EnglishLearningAgent, agent, build_english_responder
from .node import english_learning_agent_node

def get_default_agent():
    """Return the default EnglishLearningAgent instance."""
    return agent

__all__ = ["EnglishLearningAgent", "agent", "build_english_responder", "english_learning_agent_node", "get_default_agent"]
