from dotenv import load_dotenv
load_dotenv()


import os
import httpx


MCP_SERVER_URL = "https://my-mcp-server-dqbx.onrender.com/mcp"

MCP_API_KEY = "c6b3d7d988a0ce90066bc30225553b7862b36e1ab9c3f596ac2a3e1cd986768c"


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
            "user_id": "test-user",
            "key": "name"
        }
    )

    print(result)

    assert "result" in result
