from dotenv import load_dotenv
load_dotenv()

import os
import httpx


def get_config():
    load_dotenv(override=True)

    mcp_url = os.getenv("MCP_SERVER_URL")
    mcp_key = os.getenv("MCP_API_KEY")

    print("===== DEBUG MCP CONFIG =====")
    print("MCP_SERVER_URL:", mcp_url)
    print("MCP_API_KEY exists:", bool(mcp_key))

    return (
        mcp_url,
        mcp_key
    )


def call_mcp(tool_name, arguments):

    MCP_SERVER_URL, MCP_API_KEY = get_config()

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

    print("===== CALL MCP =====")
    print(MCP_SERVER_URL)

    r = httpx.post(
        MCP_SERVER_URL,
        json=payload,
        headers=headers,
        timeout=10
    )

    print("STATUS:", r.status_code)
    print("BODY:", r.text[:200])

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


def test_save_memory():

    result = call_mcp(
        "save_memory",
        {
            "user_id": "test-user",
            "key": "name",
            "value": "nonkun"
        }
    )

    assert "result" in result


def test_save_and_get_memory():

    save_result = call_mcp(
        "save_memory",
        {
            "user_id": "test-user",
            "key": "test_key",
            "value": "hello_mcp"
        }
    )

    assert "result" in save_result


    get_result = call_mcp(
        "get_memory",
        {
            "user_id": "test-user",
            "key": "test_key"
        }
    )

    assert "result" in get_result


def test_save_note_and_search_notes():

    result = call_mcp(
        "save_note",
        {
            "user_id": "test-user",
            "title": "pytestテストメモ",
            "body": "MCP検索テスト用のメモです",
            "category": "test"
        }
    )

    assert "result" in result


def test_reminder_flow():

    result = call_mcp(
        "set_reminder",
        {
            "user_id": "test-user",
            "remind_at": "2026-07-27T10:00:00+09:00",
            "message": "pytestリマインダーテスト",
            "repeat": "none"
        }
    )

    assert "result" in result