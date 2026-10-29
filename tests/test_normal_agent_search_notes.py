"""Regression tests for normal-agent MCP tool exposure."""

from agents.normal import handlers


def test_search_notes_is_exposed_to_groq_tool_schema():
    names = {
        tool.get("function", {}).get("name")
        for tool in handlers._NORMAL_MCP_TOOLS_SCHEMA
    }
    assert "search_notes" in names


def test_search_notes_is_allowed_by_normal_agent_dispatch_gate():
    assert "search_notes" in handlers._NORMAL_MCP_TOOL_NAMES
    assert "search_notes" in handlers._SAFE_INLINE_TOOLS


def test_search_notes_is_safe_read_only_fallback():
    assert "search_notes" in handlers._SAFE_FALLBACK_TOOLS
