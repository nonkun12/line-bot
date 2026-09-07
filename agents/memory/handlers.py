"""
Memory Agent handlers

MCP Memory Server interface layer
"""

import json
import re
import threading


_pending_delete_confirmation = {}
_pending_memory_target = {}
_pending_confirm_lock = threading.Lock()


_DELETE_ALL_MEMORY_PATTERN = re.compile(
    r"(記憶|memory|メモ).*(全部|すべて|全て|リセット|削除|消去)"
)


def _load_memories(user_id, call_mcp_tool):
    raw = call_mcp_tool("get_all_memory", {"user_id": user_id})
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        data = []
    return data if isinstance(data, list) else []


def _find_memory_target(message, user_id, call_mcp_tool):
    """削除対象の記憶キーを決定する。日付指定と直前の確認対象を優先する。"""
    text = (message or "").strip()

    # 「それを消して」は直前に確認した記憶を削除する。
    if text in {"それを消して", "それを削除して", "それを忘れて"}:
        with _pending_confirm_lock:
            return _pending_memory_target.get(user_id, "name")

    memories = _load_memories(user_id, call_mcp_tool)
    dates = re.findall(r"\d+月\d+日|\d+月|\d+日", text)

    if dates:
        for item in memories:
            if not isinstance(item, dict):
                continue
            value = str(item.get("value", ""))
            if value and any(date in value for date in dates):
                return item.get("key") or "memory"

    if "名前" in text:
        return "name"

    # 明示的なキーが分からない場合は、従来互換で name を対象にする。
    return "name"


def handle_save_memory(message, user_id, call_mcp_tool):
    """Save memory request"""
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
        text = re.sub(r"^覚えて\s*[:：]?\s*", "", message)
    else:
        text = message.strip()

    key = "memory"
    value = text

    m = re.search(r"(?:私の)?名前は(.+?)(?:です|、|。|$)", message)
    if m:
        key = "name"
        value = m.group(1).strip()

    return call_mcp_tool(
        "save_memory",
        {"user_id": user_id, "key": key, "value": value},
    )


def handle_delete_memory(message, user_id, call_mcp_tool):
    """Delete a single memory, including contextual follow-up requests."""
    delete_keywords = ["忘れて", "削除して", "削除する", "消して", "消す"]
    if not any(keyword in message for keyword in delete_keywords):
        return None

    key = _find_memory_target(message, user_id, call_mcp_tool)
    result = call_mcp_tool(
        "delete_memory",
        {"user_id": user_id, "key": key},
    )

    with _pending_confirm_lock:
        _pending_memory_target.pop(user_id, None)

    return result


def handle_get_name(message, user_id, call_mcp_tool):
    """Get user's name"""
    if message not in ["私の名前は？", "名前は？", "私の名前を教えて"]:
        return None

    name = call_mcp_tool("get_memory", {"user_id": user_id, "key": "name"})

    invalid_values = {"", None, "記憶がありません", "ありません", "null"}

    if name:
        try:
            name_data = json.loads(name) if isinstance(name, str) else name
            if isinstance(name_data, dict):
                name = name_data.get("value", name)
        except Exception:
            pass

    if name not in invalid_values:
        return f"あなたの名前は {name} です。"

    return "名前はまだ記憶されていません。"


def handle_get_all_memory(message, user_id, call_mcp_tool):
    """Memory query"""
    query_keywords = [
        "名前",
        "何を覚えて",
        "何を覚えてる",
        "何を覚えている",
        "覚えてる？",
        "覚えている？",
        "覚えてるの？",
        "覚えているの？",
    ]

    if not any(keyword in message for keyword in query_keywords):
        return None

    memories = call_mcp_tool("get_all_memory", {"user_id": user_id})

    try:
        data = json.loads(memories) if isinstance(memories, str) else memories
        if not data:
            return "まだ記憶している情報はありません。"

        dates = re.findall(r"\d+月\d+日|\d+月|\d+日", message)

        for item in data:
            value = str(item.get("value", ""))
            if value and any(date in value for date in dates):
                with _pending_confirm_lock:
                    _pending_memory_target[user_id] = item.get("key") or "memory"
                return f"はい、覚えています。{value}"

        lines = []
        for item in data:
            key = item.get("key", "")
            value = item.get("value", "")
            if value:
                lines.append(f"- {key}: {value}")

        return "覚えている情報は以下です。\n" + "\n".join(lines)

    except Exception as e:
        print("MEMORY GET ALL ERROR:", e)
        return "記憶の取得に失敗しました。"


def handle_delete_all_memory(message, user_id, call_mcp_tool):
    """Delete all memory confirmation flow"""
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
            _pending_delete_confirmation[user_id] = "delete_all_memory"
        return "記憶をすべて削除しますか？「はい」と送ってください"

    if message == "はい":
        with _pending_confirm_lock:
            pending = _pending_delete_confirmation.pop(user_id, None)

        if pending == "delete_all_memory":
            return call_mcp_tool("delete_all_memory", {"user_id": user_id})

    return None


def handle_memory_message(message, user_id, call_mcp_tool):
    """Main Memory Agent handler"""
    handlers = [
        handle_delete_all_memory,
        handle_save_memory,
        handle_delete_memory,
        handle_get_name,
        handle_get_all_memory,
    ]

    for handler in handlers:
        result = handler(message, user_id, call_mcp_tool)
        if result is not None:
            return result

    return None
