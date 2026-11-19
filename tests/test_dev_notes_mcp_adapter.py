from unittest.mock import patch

from dev_notes.mcp_notes_adapter import McpNotesLogAdapter


def test_mcp_notes_adapter_calls_save_note():
    adapter = McpNotesLogAdapter()

    with patch("mcp_client.call_mcp_tool") as mock_call:
        adapter.log_execution(
            agent_name="testagent",
            state={"foo": "bar"},
            result={"ok": True},
            error=None,
            category="agent_execution_log",
            metadata={"role": "graph_node"},
        )

        # Ensure save_note was called on the MCP client
        mock_call.assert_called_once()

        called_args, called_kwargs = mock_call.call_args

        assert called_args[0] == "save_note"
        params = called_args[1]

        assert params["user_id"] == "system-agent-log"
        assert params["category"] == "agent_execution_log"
        assert params["title"].startswith("Agent execution: testagent")

        # Content should include a serialized payload containing agent_name and state/result
        content = params.get("content", "")
        assert "testagent" in content
        assert "'agent_name'" in content or '"agent_name"' in content
        assert "foo" in content
        assert "bar" in content
        assert "ok" in content
