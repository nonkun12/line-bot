import re
import unicodedata


def handle_list_notes(user_id, call_mcp_tool):
    """メモ一覧を取得する。"""
    return call_mcp_tool(
        "search_notes",
        {
            "user_id": user_id,
            "keyword": "",
        },
    )


def handle_search_notes(message, user_id, call_mcp_tool):
    """キーワードによるメモ検索を実行する。"""
    keyword = re.sub(r"^メモ検索\s*[:：]?\s*", "", message)
    if not keyword:
        return "検索キーワードを指定してください。\n例: メモ検索 テニス"
    return call_mcp_tool(
        "search_notes",
        {
            "user_id": user_id,
            "keyword": keyword,
        },
    )


def handle_natural_note_search(message, user_id, call_mcp_tool):
    """自然文に含まれるキーワードでメモ検索を実行する。"""
    if "私のメモ" in message:
        keyword = ""
    else:
        keyword = (
            message
            .replace("LINE Botのメモを探して", "")
            .replace("メモを探して", "")
            .replace("メモを見せて", "")
            .replace("メモ", "")
            .replace("を見せて", "")
            .replace("を検索して", "")
            .replace("検索", "")
            .replace("探して", "")
            .replace("見せて", "")
            .strip()
        )

    return call_mcp_tool(
        "search_notes",
        {
            "user_id": user_id,
            "keyword": keyword,
        },
    )


def handle_save_note(message, user_id, call_mcp_tool):
    """明示的なメモ保存を実行する。"""
    body = re.sub(r"^メモして\s*[:：]?\s*", "", message)

    # 簡易カテゴリ判定
    if any(k in body.lower() for k in ["python", "program", "プログラム", "ai", "コード"]):
        category = "技術"
    elif any(k in body for k in ["勉強", "英語", "資格", "学習"]):
        category = "学習"
    elif any(k in body for k in ["予定", "予約", "会議", "行く"]):
        category = "予定"
    elif any(k in body for k in ["買う", "購入", "買い物"]):
        category = "生活"
    else:
        category = "一般"

    return call_mcp_tool(
        "save_note",
        {
            "user_id": user_id,
            "title": "LINEメモ",
            "body": body,
            "category": category,
        },
    )


def handle_auto_save_note(message, user_id, call_mcp_tool):
    """予定・目標系などのキーワードを検出し、自動でメモ保存を実行する。"""
    if (
        ("予定" in message or "したい" in message or "忘れないように" in message)
        and len(message) > 5
        and not any(q in message for q in [
            "ある？",
            "ありますか",
            "あるか",
            "あった？",
            "あったか",
            "確認",
            "教えて",
            "覚えて",
        ])
    ):
        return call_mcp_tool(
            "save_note",
            {
                "user_id": user_id,
                "title": "自動メモ",
                "body": message,
                "category": "一般",
            },
        )
    return None


def handle_delete_note(message, user_id, call_mcp_tool):
    """個別メモ削除処理（自然文指定、および明示的ID指定）を実行する。"""
    # 1. 自然文メモ削除
    m = re.search(r"(\d+)番.*メモ.*削除", message)
    if m:
        note_id = m.group(1)
        return call_mcp_tool(
            "delete_note",
            {
                "user_id": user_id,
                "id": note_id,
            },
        )

    # 2. 明示的なID指定メモ削除
    if message.startswith("メモ削除"):
        note_id = message.replace("メモ削除", "").strip()
        note_id = unicodedata.normalize("NFKC", note_id)

        if not note_id:
            return "削除するメモIDを指定してください。\n例: メモ削除25"

        print("DELETE DEBUG user_id=", user_id, "note_id=", note_id)

        return call_mcp_tool(
            "delete_note",
            {
                "user_id": user_id,
                "id": note_id,
            },
        )

    return None
