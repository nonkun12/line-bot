"""
Memory Agent intent detection
"""

def is_memory_intent(message: str) -> bool:
    """
    Memory関連リクエスト判定
    """

    keywords = [
        "覚えて",
        "記憶",
        "忘れて",
        "何を覚えて",
        "名前",
        "私の情報",
    ]

    return any(
        keyword in message
        for keyword in keywords
    )


def is_memory_save(message: str) -> bool:
    return "覚えて" in message


def is_memory_delete(message: str) -> bool:
    return "忘れて" in message


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