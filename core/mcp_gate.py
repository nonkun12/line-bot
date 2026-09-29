"""MCP capability gate.

All MCP tool execution should enter through this module.  The gate is
fail-closed: unknown tools are rejected before network I/O, tool-level
isError responses are failures, and transport/time-out failures are marked
unknown so callers must not report an unverified write as successful.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping

from mcp_client import call_mcp_tool as _raw_call_mcp_tool


READ_TOOLS = frozenset({
    "get_memory",
    "get_all_memory",
    "search_notes",
    "list_reminders",
    "get_today_schedule",
})

WRITE_TOOLS = frozenset({
    "save_memory",
    "save_note",
    "set_reminder",
})

DESTRUCTIVE_TOOLS = frozenset({
    "delete_memory",
    "delete_all_memory",
    "delete_note",
    "cancel_reminder",
})

ALLOWED_TOOLS = READ_TOOLS | WRITE_TOOLS | DESTRUCTIVE_TOOLS


@dataclass(frozen=True)
class GateResult:
    status: str
    tool_name: str
    data: str = ""
    operation_id: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class MCPGateError(RuntimeError):
    """Base class for fail-closed MCP gate failures."""


class MCPRejected(MCPGateError):
    """The request was rejected before MCP execution."""


class MCPFailed(MCPGateError):
    """MCP returned a definite failure."""


class MCPUnknown(MCPGateError):
    """Execution outcome could not be established safely."""


def _timeout(timeout: float | None) -> float:
    if timeout is not None:
        return float(timeout)
    try:
        value = float(os.getenv("MCP_TIMEOUT_SEC", "10"))
    except ValueError:
        value = 10.0
    return max(1.0, min(value, 30.0))


def execute_mcp_tool(
    tool_name: str,
    arguments: Mapping[str, Any] | None = None,
    *,
    timeout: float | None = None,
) -> GateResult:
    if not isinstance(tool_name, str) or tool_name not in ALLOWED_TOOLS:
        return GateResult(
            status="rejected",
            tool_name=str(tool_name),
            error="MCP tool is not allowlisted",
        )

    if not isinstance(arguments, Mapping):
        return GateResult(
            status="rejected",
            tool_name=tool_name,
            error="MCP arguments must be an object",
        )

    try:
        data = _raw_call_mcp_tool(
            tool_name,
            dict(arguments),
            timeout=_timeout(timeout),
        )
    except TimeoutError as exc:
        return GateResult(
            status="unknown",
            tool_name=tool_name,
            error=f"MCP timeout: {exc}",
        )
    except MCPGateError:
        raise
    except Exception as exc:
        # A network/transport exception does not prove whether a write reached
        # the server.  Keep the result unknown rather than inventing failure
        # or retrying a potentially duplicated side effect.
        return GateResult(
            status="unknown" if tool_name in WRITE_TOOLS | DESTRUCTIVE_TOOLS else "failed",
            tool_name=tool_name,
            error=f"{type(exc).__name__}: {exc}",
        )


def call_mcp_tool(
    tool_name: str,
    arguments: Mapping[str, Any] | None = None,
    timeout: float | None = None,
) -> str:
    """Compatibility wrapper returning the legacy text result on success.

    Callers that need to distinguish unknown/rejected/failed outcomes should
    use execute_mcp_tool() directly.
    """
    result = execute_mcp_tool(tool_name, arguments, timeout=timeout)
    if result.status == "ok":
        return result.data
    if result.status == "rejected":
        raise MCPRejected(result.error or "MCP request rejected")
    if result.status == "unknown":
        raise MCPUnknown(result.error or "MCP outcome unknown")
    raise MCPFailed(result.error or "MCP request failed")


__all__ = [
    "ALLOWED_TOOLS",
    "DESTRUCTIVE_TOOLS",
    "GateResult",
    "MCPFailed",
    "MCPGateError",
    "MCPRejected",
    "MCPUnknown",
    "READ_TOOLS",
    "WRITE_TOOLS",
    "call_mcp_tool",
    "execute_mcp_tool",
]
