from dotenv import load_dotenv
load_dotenv()


import os
import httpx


def get_config():
    load_dotenv(override=True)

    return (
        os.environ["MCP_SERVER_URL"],
        os.environ["MCP_API_KEY"]
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


def test_save_memory():
    result = call_mcp(
        "save_memory",
        {
            "user_id": "test-user",
            "key": "name",
            "value": "nonkun"
        }
    )

    print(result)

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

    print(get_result)


def test_save_note_and_search_notes():
    save_result = call_mcp(
        "save_note",
        {
            "user_id": "test-user",
            "title": "pytestテストメモ",
            "body": "MCP検索テスト用のメモです",
            "category": "test"
        }
    )

    assert "result" in save_result

    search_result = call_mcp(
        "search_notes",
        {
            "user_id": "test-user",
            "keyword": "MCP検索"
        }
    )

    assert "result" in search_result

    print(search_result)


def test_reminder_flow():
    set_result = call_mcp(
        "set_reminder",
        {
            "user_id": "test-user",
            "remind_at": "2026-07-27T10:00:00+09:00",
            "message": "pytestリマインダーテスト",
            "repeat": "none"
        }
    )

    assert "result" in set_result

    list_result = call_mcp(
        "list_reminders",
        {
            "user_id": "test-user"
        }
    )

    assert "result" in list_result

    print(list_result)

    cancel_result = call_mcp(
        "cancel_reminder",
        {
            "user_id": "test-user",
            "id": 1
        }
    )

    assert "result" in cancel_result

    print(cancel_result)
