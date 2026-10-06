import mcp_client
from agents.notes.handlers import handle_natural_note_search


def test_note_read_failure_is_explicit():
    def fail(tool, arguments):
        raise RuntimeError("temporary MCP failure")
    result = handle_natural_note_search("MCPでメモを検索して", "test-user", fail)
    assert "一時的に利用できません" in result
    assert "AIサービス" not in result


def test_note_search_normalizes_particle():
    seen = {}
    def fake(tool, arguments):
        seen.update(arguments)
        return []
    assert handle_natural_note_search("MCPでメモを検索して", "test-user", fake) == []
    assert seen["keyword"] == "MCP"


def test_retry_settings_are_finite(monkeypatch):
    monkeypatch.setenv("MCP_HIBERNATE_RETRY_MAX_SEC", "inf")
    monkeypatch.setenv("MCP_HIBERNATE_RETRY_INTERVAL_SEC", "nan")
    max_wait, interval = mcp_client._hibernate_retry_settings()
    assert max_wait == 120.0
    assert interval == 60.0


def test_only_one_hibernate_wake_owner():
    mcp_client._HIBERNATE_COOLDOWN_UNTIL = 0.0
    mcp_client._HIBERNATE_WAKE_OWNER = False
    assert mcp_client._claim_hibernate_wake() is True
    assert mcp_client._claim_hibernate_wake() is False
    mcp_client._release_hibernate_wake(0.0)


def test_dashboard_system_source_has_no_mcp_calls():
    from inspect import getsource
    from routes.dashboard import system_status
    source = getsource(system_status)
    assert "call_mcp_tool(" not in source
