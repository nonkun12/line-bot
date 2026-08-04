import re


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
