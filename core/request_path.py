"""Incremental request path from the shared Supervisor into the Core graph."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.langgraph_runtime import CoreGraphState
from graph.core_graph import build_current_core_graph
from graph.supervisor import supervisor_node


def run_core_request(
    user_id: str,
    message: str,
    *,
    call_mcp_tool=None,
) -> dict[str, Any]:
    """Classify with the existing Supervisor, then execute the selected agent via Core."""
    initial: CoreGraphState = {
        "user_id": user_id,
        "raw_message": message,
        "agent_results": {},
    }
    if call_mcp_tool is not None:
        initial["call_mcp_tool"] = call_mcp_tool  # type: ignore[typeddict-item]

    classified = supervisor_node(initial)  # type: ignore[arg-type]
    return dict(build_current_core_graph().invoke(classified))


def extract_core_reply(result: Mapping[str, Any]) -> str:
    """Return the Core final reply as text."""
    value = result.get("final_reply")
    if isinstance(value, str):
        return value
    return "Agent結果なし"
