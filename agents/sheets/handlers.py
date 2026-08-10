"""
Google Sheets Agent handlers
"""

from agents.sheets.client import GoogleSheetsClient
from ai_client import generate_chat_completion


# 「見て」「読んで」だけの単純な一覧表示ではなく、シートの内容を
# AIに理解・分析させた上で自然文で回答してほしいことを示すキーワード。
# これらが含まれる場合は、Read(生データ一覧表示)より優先してAI分析を行う。
_AI_ANALYSIS_TRIGGER_KEYWORDS = [
    "分析",
    "まとめ",
    "要約",
    "教えて",
    "重要",
    "について",
    "どんな",
    "何が",
    "何を",
    "内容を",
]


def _is_ai_analysis_request(message: str) -> bool:
    return any(
        keyword in message
        for keyword in _AI_ANALYSIS_TRIGGER_KEYWORDS
    )


def _format_sheet_rows_for_ai(rows: list) -> str:
    if not rows:
        return "(シートにはまだデータがありません)"

    lines = []

    for index, row in enumerate(rows, start=1):
        lines.append(
            f"{index}. " + " | ".join(str(cell) for cell in row)
        )

    return "\n".join(lines)


def generate_ai_sheet_reply(message: str, rows: list) -> str:
    """
    Google Sheetsの現在の内容をコンテキストとしてAIへ渡し、
    ユーザーの質問に対する自然な回答を生成する。

    既存プロジェクトのAI呼び出し方法(ai_client.generate_chat_completion /
    Groq)をそのまま利用し、新しいAIサービスは追加しない。
    """

    sheet_content = _format_sheet_rows_for_ai(rows)

    system_prompt = (
        "あなたは優秀で親しみやすいAI秘書です。\n"
        "以下はユーザーのGoogle Sheetsに記録されている現在の内容です。\n\n"
        f"【Google Sheetsの内容】\n{sheet_content}\n\n"
        "このデータだけを事実として使い、ユーザーの質問に日本語で自然に答えてください。\n"
        "データに書かれていないことは推測せず、\n"
        "「シートにはその情報が見当たりませんでした」のように正直に伝えてください。"
    )

    try:
        response = generate_chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message},
            ],
            temperature=0.3,
            max_tokens=700,
        )

        return response.choices[0].message.content
    except Exception as e:
        print("SHEETS AI ANALYSIS ERROR:", e)

        return (
            "シートの内容は確認できましたが、"
            "AIによる回答生成中にエラーが発生しました。"
            "少し時間をおいてもう一度お試しください。"
        )


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

    # Delete
    if "削除して" in message or (
        "シートから" in message and "削除" in message
    ):
        keyword = message

        if "シートから" in keyword:
            keyword = keyword.split("シートから", 1)[1]
        elif "シートを" in keyword:
            keyword = keyword.split("シートを", 1)[1]

        for suffix in [
            "を削除して",
            "を削除する",
            "削除して",
            "削除する",
        ]:
            if suffix in keyword:
                keyword = keyword.split(suffix, 1)[0]
                break

        keyword = keyword.strip()

        if not keyword:
            return {
                "text": "削除する内容を指定してください。",
                "success": False,
            }

        rows = client.search("A:Z", keyword)

        if not rows:
            return {
                "text": f"削除対象が見つかりませんでした：{keyword}",
                "success": False,
            }

        client.delete_row(keyword)

        return {
            "text": f"Google Sheetsから削除しました：{keyword}",
            "success": True,
        }

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

    # AI Analysis
    # 「シートの内容を分析して」「重要な予定を教えて」のような自然文の
    # 質問は、単なる一覧表示ではなくAIにシートの内容を理解・判断させた
    # 上で回答させる。Read(単純な一覧表示)より優先して判定する。
    if _is_ai_analysis_request(message):
        rows = client.read_rows("A:Z")
        reply_text = generate_ai_sheet_reply(message, rows)

        return {
            "text": reply_text,
            "rows": rows,
            "success": True,
        }

    # Read
    if "見て" in message or "読んで" in message:
        rows = client.read_rows("A:Z")

        if not rows:
            return {
                "text": "Google Sheetsにはデータがありません。",
                "rows": [],
                "success": True,
            }

        lines = ["Google Sheetsの内容："]

        for index, row in enumerate(rows, start=1):
            lines.append(
                f"{index}. " + " | ".join(str(cell) for cell in row)
            )

        return {
            "text": "\n".join(lines),
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
