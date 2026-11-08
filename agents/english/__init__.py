"""Public English-learning agent exports.

The package-level ``agent`` keeps the historical ``english`` contract.
The richer follow-up implementation remains available from ``agents.english.node``.
"""

from agents.english_agent import EnglishLearningAgent, agent, build_english_responder
from .node import english_learning_agent_node

__all__ = ["EnglishLearningAgent", "agent", "build_english_responder", "english_learning_agent_node", "create_agent"]

def create_agent():
    """Return the default English learning agent instance.

    This helper provides a convenient way to obtain the agent without
    importing the underlying implementation directly. It simply returns
    the ``agent`` object exported from :mod:`agents.english_agent`.
    """
    return agent
