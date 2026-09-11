"""Incremental request path from the shared Supervisor into the Core graph."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.langgraph_runtime import CoreGraphState
from graph.core_graph import build_current_core_graph
from graph.supervisor import supervisor_node
from e2e_status import StepTimer, record_step


def run_core_request(
    user_id: str,
    message: str,
    *,
    channel: str = "unknown",
    metadata: Mapping[str, Any] | None = None,
    call_mcp_tool=None,
) -> dict[str, Any]:
    """Classify with the existing Supervisor, then execute the selected agent via Core."""
    initial: CoreGraphState = {
        "user_id": user_id,
        "raw_message": message,
        "channel": channel,
        "metadata": dict(metadata or {}),
        "agent_results": {},
    }
    if call_mcp_tool is not None:
        initial["call_mcp_tool"] = call_mcp_tool  # type: ignore[typeddict-item]

    # LINE input is recorded at the actual channel-to-Core handoff, before any
    # Core/Agent work begins. Non-LINE channels do not affect the LINE E2E path.
    if channel == "line":
        record_step("line_in", True, http_status=200, error_location="core/request_path.line_input")

    with StepTimer("core") as core_timer:
        try:
            classified = supervisor_node(initial)  # type: ignore[arg-type]
        except Exception as exc:
            core_timer.fail(error=exc, error_location="core/request_path.supervisor")
            raise

        with StepTimer("agent") as agent_timer:
            try:
                result = dict(build_current_core_graph().invoke(classified))
            except Exception as exc:
                agent_timer.fail(error=exc, error_location="core/request_path.agent")
                core_timer.fail(error=exc, error_location="core/request_path.agent")
                raise

        agent_timer.ok()
        core_timer.ok()
        return result


def extract_core_reply(result: Mapping[str, Any]) -> str:
    """Return the Core final reply as text."""
    value = result.get("final_reply")
    if isinstance(value, str):
        return value
    return "Agent結果なし"
