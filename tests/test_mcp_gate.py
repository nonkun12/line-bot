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


def test_direct_mcp_imports_are_forbidden():
    from pathlib import Path
    import ast

    root = Path(__file__).resolve().parents[1]
    allowed = {root / "mcp_client.py", root / "core" / "mcp_gate.py"}
    forbidden = []
    for path in root.rglob("*.py"):
        if path in allowed or ".git" in path.parts or path.name.startswith("test_") or path.parts[-2:] == ("tests", path.name):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(alias.name == "mcp_client" for alias in node.names):
                    forbidden.append(str(path.relative_to(root)))
            elif isinstance(node, ast.ImportFrom) and node.module == "mcp_client":
                forbidden.append(str(path.relative_to(root)))
    assert forbidden == []
