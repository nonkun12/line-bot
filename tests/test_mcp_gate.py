from core import mcp_gate


def test_unknown_tool_is_rejected_without_network(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("network call must not happen")

    monkeypatch.setattr(mcp_gate, "_raw_call_mcp_tool", fail)
    result = mcp_gate.execute_mcp_tool("not_allowlisted", {})
    assert result.status == "rejected"


def test_write_transport_failure_is_unknown(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("connection failed")

    monkeypatch.setattr(mcp_gate, "_raw_call_mcp_tool", fail)
    result = mcp_gate.execute_mcp_tool("save_memory", {"user_id": "u"})
    assert result.status == "unknown"


def test_read_transport_failure_is_failed(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("connection failed")

    monkeypatch.setattr(mcp_gate, "_raw_call_mcp_tool", fail)
    result = mcp_gate.execute_mcp_tool("get_memory", {"user_id": "u"})
    assert result.status == "failed"


def test_tool_level_error_is_failed(monkeypatch):
    def fail(*args, **kwargs):
        raise mcp_gate.MCPToolError("tool rejected")

    monkeypatch.setattr(mcp_gate, "_raw_call_mcp_tool", fail)
    result = mcp_gate.execute_mcp_tool("save_memory", {"user_id": "u"})
    assert result.status == "failed"


def test_success_preserves_legacy_text_contract(monkeypatch):
    monkeypatch.setattr(
        mcp_gate,
        "_raw_call_mcp_tool",
        lambda *args, **kwargs: "saved",
    )
    result = mcp_gate.execute_mcp_tool("save_memory", {"user_id": "u"})
    assert result.status == "ok"
    assert result.data == "saved"
    assert mcp_gate.call_mcp_tool("save_memory", {"user_id": "u"}) == "saved"
