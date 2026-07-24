
import os
import httpx


MCP_SERVER_URL = os.environ["MCP_SERVER_URL"]
MCP_API_KEY = os.environ["MCP_API_KEY"]


def call_mcp(tool_name, arguments):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments
        }
    }

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "x-api-key": MCP_API_KEY
    }

    r = httpx.post(
        MCP_SERVER_URL,
        json=payload,
        headers=headers,
        timeout=10
    )

    r.raise_for_status()
    return r.json()


def test_get_memory():
    result = call_mcp(
        "get_memory",
        {
            "user_id": "test-user"
        }
    )

    print(result)

    assert "result" in result
