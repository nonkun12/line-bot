"""
LangGraph Phase1: State定義
"""

from typing import Any, Optional
from typing_extensions import TypedDict


class AgentState(TypedDict, total=False):

    user_id: str
    raw_message: str

    intent: Optional[str]
    next_agent: Optional[str]

    agent_results: dict[str, Any]

    final_reply: Optional[str]

    error: Optional[str]
    