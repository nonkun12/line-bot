"""
LangGraph Phase1: State definition.

The same AgentState is also used by the bounded overnight Worker graph.
"""

from typing import Any, Callable, Optional
from typing_extensions import TypedDict


class AgentState(TypedDict, total=False):

    user_id: str
    raw_message: str
    request_id: str
    call_mcp_tool: Callable[..., Any]

    # Overnight Worker identity/isolation context.
    job_id: int
    job_type: str
    workdir: str

    intent: Optional[str]
    next_agent: Optional[str]

    agent_results: dict[str, Any]

    final_reply: Optional[str]

    error: Optional[str]
    development_error: Optional[str]

    # Phase4a: patch application / pytest results
    patch_result: Optional[dict[str, Any]]
    test_result: Optional[dict[str, Any]]

    # Phase3: Fix Agent results -> generated Patch candidates
    patch_candidates: Optional[list[dict[str, Any]]]

    # Phase1: approval status (pending / expired / none)
    pending_status: Optional[str]

    # Overnight Worker publication, review, merge, and deployment results.
    commit_result: Optional[dict[str, Any]]
    publish_result: Optional[dict[str, Any]]
    review_result: Optional[dict[str, Any]]
    merge_result: Optional[dict[str, Any]]
    deploy_result: Optional[dict[str, Any]]
