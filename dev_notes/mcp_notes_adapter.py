from __future__ import annotations

from typing import Any, Dict, Optional

from .base import DevNotesLogAdapter
from .schema import ExecutionLogEntry, DEFAULT_CATEGORY


class McpNotesLogAdapter(DevNotesLogAdapter):
    """
    MCP Memory backed logging adapter.

    Uses existing mcp_client.call_mcp_tool().
    Logging failures never affect agent execution.
    """

    def log_execution(
        self,
        agent_name: str,
        state: Dict[str, Any],
        result: Any,
        error: Optional[BaseException] = None,
        category: str = DEFAULT_CATEGORY,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:

        try:
            import mcp_client

            entry = ExecutionLogEntry(
                category=category,
                agent_name=agent_name,
                state=state or {},
                result=result,
                error=error,
                metadata=metadata or {},
            )

            payload = entry.to_dict()

            mcp_client.call_mcp_tool(
                "save_note",
                {
                    "user_id": "system-agent-log",
                    "title": f"Agent execution: {agent_name}",
                    "content": str(payload),
                    "category": "agent_execution_log",
                },
            )

        except Exception:
            # Logging must never break agent execution.
            return
