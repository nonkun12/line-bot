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

import httpx
import mcp_client
from mcp_client import MCPToolError


READ_TOOLS = frozenset({
    "get_memory",
    "get_all_memory",
    "search_notes",
    "list_notes",
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
    "delete_all_notes",
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


def _raw_call_mcp_tool(*args: Any, **kwargs: Any) -> Any:
    """Indirection preserves test doubles while keeping MCP access centralized."""
    return mcp_client.call_mcp_tool(*args, **kwargs)


def _timeout(timeout: float | None) -> float:
    if timeout is not None:
        return max(1.0, min(float(timeout), 30.0))
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
        return GateResult(
            status="ok",
            tool_name=tool_name,
            data=data,
        )
    except httpx.TimeoutException as exc:
        return GateResult(
            status="unknown",
            tool_name=tool_name,
            error=f"MCP timeout: {exc}",
        )
    except MCPToolError:
        return GateResult(
            status="failed",
            tool_name=tool_name,
            error="MCP tool reported an error",
        )
    except MCPGateError:
        raise
    except Exception as exc:
        return GateResult(
            status="unknown" if tool_name in WRITE_TOOLS | DESTRUCTIVE_TOOLS else "failed",
            tool_name=tool_name,
            error=f"{type(exc).__name__}: {exc}",
        )


def parse_mcp_json_list(raw: Any) -> Any:
    """Parse legacy MCP list responses without performing MCP I/O."""
    return mcp_client.parse_mcp_json_list(raw)


def call_mcp_tool(
    tool_name: str,
    arguments: Mapping[str, Any] | None = None,
    timeout: float | None = None,
) -> str:
    """Compatibility wrapper returning the legacy text result on success."""
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
    "parse_mcp_json_list",
    "execute_mcp_tool",
]
