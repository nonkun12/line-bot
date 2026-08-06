"""
Memory Agent handlers

MCP Memory Server interface layer
"""

import json
import re
import threading


_pending_delete_confirmation = {}
_pending_confirm_lock = threading.Lock()


_DELETE_ALL_MEMORY_PATTERN = re.compile(
    r"(記憶|memory|メモ).*(全部|すべて|全て|リセット|削除|消去)"
)


def handle_save_memory(
    message,
    user_id,
    call_mcp_tool,
):
    """
    Save memory request
    """

    if (
        "覚えて" not in message
        and "覚えといて" not in message
        and "覚えてる？" not in message
        and "覚えている？" not in message
    ):
        return None

    if (
        ("明日" in message and "時" in message)
        or "教えて" in message
        or "覚えていること" in message
        or "覚えてること" in message
        or "何を覚えてる" in message
        or "何を覚えている" in message
        or "覚えてる？" in message
        or "覚えている？" in message
    ):
        return None

    if message.startswith("覚えて"):
        text = re.sub(
            r"^覚えて\s*[:：]?\s*",
            "",
            message
        )
    else:
        text = message.strip()

    key = "memory"
    value = text

    m = re.search(
        r"(?:私の)?名前は(.+?)(?:です|、|。|$)",
        message
    )

    if m:
        key = "name"
        value = m.group(1).strip()

    return call_mcp_tool(
        "save_memory",
        {
            "user_id": user_id,
            "key": key,
            "value": value,
        }
    )


def handle_delete_memory(
    message,
    user_id,
    call_mcp_tool,
):
    """
    Delete single memory
    """

    if "忘れて" not in message:
        return None

    return call_mcp_tool(
        "delete_memory",
        {
            "user_id": user_id,
            "key": "name",
        }
    )


def handle_get_name(
    message,
    user_id,
    call_mcp_tool,
):
    """
    Get user's name
    """

    if message not in [
        "私の名前は？",
        "名前は？",
        "私の名前を教えて",
    ]:
        return None

    name = call_mcp_tool(
        "get_memory",
        {
            "user_id": user_id,
            "key": "name",
        }
    )

    if name:
        try:
            if isinstance(name, str):
                name_data = json.loads(name)
            else:
                name_data = name

            if isinstance(name_data, dict):
                name = name_data.get(
                    "value",
                    name
                )

        except Exception:
            pass

        return f"あなたの名前は {name} です。"

    return "名前はまだ記憶されていません。"


def handle_get_all_memory(
    message,
    user_id,
    call_mcp_tool,
):
    """
    Memory query
    """

    if "名前" not in message:
        return None

    memories = call_mcp_tool(
        "get_all_memory",
        {
            "user_id": user_id,
        }
    )

    try:
        if isinstance(memories, str):
            data = json.loads(memories)
        else:
            data = memories

        for item in data:
            if item.get("key") == "name":
                return f"あなたの名前は {item.get('value')} です。"

    except Exception:
        pass

    return "名前はまだ記憶されていません。"


def handle_delete_all_memory(
    message,
    user_id,
    call_mcp_tool,
):
    """
    Delete all memory confirmation flow
    """

    if (
        message in [
            "記憶全部削除",
            "記憶をすべて削除",
            "記憶を全部削除",
            "全ての記憶を削除",
            "全部の記憶を削除",
            "memoryを全部削除して",
            "保存しているメモを全部削除して",
            "保存している記憶を消して",
            "覚えていること全部消して",
            "覚えていることを全部削除して",
            "記憶をリセットして",
            "memoryをリセットして",
        ]
        or _DELETE_ALL_MEMORY_PATTERN.search(message)
    ):

        with _pending_confirm_lock:
            _pending_delete_confirmation[user_id] = (
                "delete_all_memory"
            )

        return (
            "記憶をすべて削除しますか？"
            "「はい」と送ってください"
        )


    if message == "はい":

        with _pending_confirm_lock:
            pending = (
                _pending_delete_confirmation.pop(
                    user_id,
                    None
                )
            )

        if pending == "delete_all_memory":

            return call_mcp_tool(
                "delete_all_memory",
                {
                    "user_id": user_id
                }
            )

    return None


def handle_memory_message(
    message,
    user_id,
    call_mcp_tool,
):
    """
    Main Memory Agent handler
    """

    handlers = [
        handle_delete_all_memory,
        handle_save_memory,
        handle_delete_memory,
        handle_get_name,
        handle_get_all_memory,
    ]

    for handler in handlers:
        result = handler(
            message,
            user_id,
            call_mcp_tool,
        )

        if result is not None:
            return result

    return None