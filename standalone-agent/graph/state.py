"""
LangGraph Phase1: State定義
"""

from typing import Any, Callable, Optional
from typing_extensions import TypedDict


class AgentState(TypedDict, total=False):

    user_id: str
    raw_message: str
    request_id: str
    call_mcp_tool: Callable[..., Any]

    intent: Optional[str]
    next_agent: Optional[str]

    agent_results: dict[str, Any]

    final_reply: Optional[str]

    error: Optional[str]

    # Phase4a: patch適用 / pytest実行結果
    patch_result: Optional[dict[str, Any]]
    test_result: Optional[dict[str, Any]]

    # Phase3: Fix Agent結果から生成したPatch候補(適用は行わない)
    patch_candidates: Optional[list[dict[str, Any]]]

    # Phase1: 承認状態判定（pending / expired / none）
    pending_status: Optional[str]
