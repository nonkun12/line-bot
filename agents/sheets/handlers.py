"""
Google Sheets Agent handlers
"""

from agents.sheets.client import GoogleSheetsClient


def handle_sheets_message(
    message: str,
    user_id: str,
    client: GoogleSheetsClient,
):
    """
    Google Sheets request handler.
    """

    if not message:
        return None

    # Search
    if "検索" in message:
        keyword = (
            message
            .replace("シートから検索", "")
            .replace("シートを検索", "")
            .strip()
        )

        if not keyword:
            return {
                "text": "検索するキーワードを指定してください。",
                "success": False,
            }

        rows = client.search("A:Z", keyword)

        return {
            "text": f"検索結果：{len(rows)}件",
            "rows": rows,
            "success": True,
        }

    # Read
    if "見て" in message or "読んで" in message:
        rows = client.read_rows("A:Z")

        return {
            "text": f"Google Sheetsを読み取りました：{len(rows)}行",
            "rows": rows,
            "success": True,
        }

    # Append
    if "記録" in message or "追加" in message:
        prefix_list = [
            "シートに記録",
            "シートに追加",
            "Google Sheetsに記録",
            "Googleスプレッドシートに記録",
        ]

        content = message

        for prefix in prefix_list:
            if prefix in content:
                content = content.replace(prefix, "", 1).strip()
                break

        if not content:
            return {
                "text": "記録する内容を指定してください。",
                "success": False,
            }

        client.append_row("A:A", [content])

        return {
            "text": f"Google Sheetsに記録しました：{content}",
            "success": True,
        }

    return None
