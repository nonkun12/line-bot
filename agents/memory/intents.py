"""
Memory Agent intent detection
"""

import re


def is_memory_intent(message: str) -> bool:
    """
    Memory関連リクエスト判定
    """
    text = (message or "").strip()

    # 「ID65消して」のようなID指定はメモ削除として扱う。
    # Memory Agentが名前の記憶を誤って削除しないよう、明示的に除外する。
    if re.match(r"^ID\s*\d+\s*(?:を)?(?:消して|消す|削除して|削除する|削除)$", text, re.IGNORECASE):
        return False

    # 日付付きの「予定を消して」は、記憶している予定を削除する意図として扱う。
    if re.search(r"\d{1,2}月\d{1,2}日.*(?:予定|用事|予約).*(?:消して|消す|削除)", text):
        return True

    keywords = [
        "覚えて",
        "記憶",
        "忘れて",
        "何を覚えて",
        "名前",
        "私の情報",
        "それを消して",
        "それを削除して",
        "それを忘れて",
    ]

    return any(
        keyword in text
        for keyword in keywords
    )


def is_memory_save(message: str) -> bool:
    return "覚えて" in message


def is_memory_delete(message: str) -> bool:
    keywords = [
        "忘れて",
        "削除して",
        "削除する",
        "消して",
        "消す",
    ]

    return any(
        keyword in message
        for keyword in keywords
    )


def is_memory_query(message: str) -> bool:
    keywords = [
        "何を覚えて",
        "名前",
        "私の情報",
    ]

    return any(
        keyword in message
        for keyword in keywords
    )
