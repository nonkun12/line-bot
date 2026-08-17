"""
Google Sheets Agent handlers
"""

import re

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
    "順位",
    "整理",
    "タスク",
    "やるべきこと",
    "アドバイス",
]


def _is_ai_analysis_request(message: str) -> bool:
    return any(
        keyword in message
        for keyword in _AI_ANALYSIS_TRIGGER_KEYWORDS
    )


# 「シート」「Google Sheets」だけのような、具体的な操作意図がない
# メッセージはAI分析へフォールバックさせない。
_GENERIC_SHEET_MENTION_ONLY_PATTERN = re.compile(
    r"^(?:シート|Google Sheets|Googleスプレッドシート)[。！？!?]*$"
)


# AI分析へ渡すシート行数の上限。元のrowsは切り詰めず、AIコンテキスト
# のみを制限することで既存の一覧表示・検索等への影響を避ける。
_MAX_ROWS_FOR_AI = 200


# 「見て」「読んで」に加え、「シートの内容は？」「シートを確認して」のような
# 自然な言い回しでも、既存のRead処理(生データ一覧表示)を呼び出せるように
# するためのキーワード集。
_READ_TRIGGER_KEYWORDS = [
    "見て",
    "読んで",
    "見せて",
    "確認して",
    "内容は",
    "内容が",
    "中身",
]


def _is_read_request(message: str) -> bool:
    return any(
        keyword in message
        for keyword in _READ_TRIGGER_KEYWORDS
    )


def _format_sheet_rows_for_ai(rows: list) -> str:
    if not rows:
        return "(シートにはまだデータがありません)"

    total_rows = len(rows)
    is_truncated = total_rows > _MAX_ROWS_FOR_AI
    display_rows = rows[:_MAX_ROWS_FOR_AI] if is_truncated else rows

    lines = []

    for index, row in enumerate(display_rows, start=1):
        lines.append(
            f"{index}. " + " | ".join(str(cell) for cell in row)
        )

    if is_truncated:
        lines.append(
            f"\n(※シートの行数が多いため、全{total_rows}行のうち"
            f"先頭{_MAX_ROWS_FOR_AI}行のみを対象に回答しています)"
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


_APPEND_PREFIXES = [
    "シートに記録",
    "シートに追加",
    "Google Sheetsに記録",
    "Googleスプレッドシートに記録",
]

_APPEND_START_MARKERS = [
    "Googleスプレッドシートに",
    "Google Sheetsに",
    "シートに",
]

_APPEND_END_MARKERS = [
    "を記録して",
    "を記録する",
    "を記録",
    "を追加して",
    "を追加する",
    "を追加",
    "記録して",
    "記録する",
    "記録",
    "追加して",
    "追加する",
    "追加",
]


def _extract_append_content(message: str) -> str:
    """
    「シートに記録して」系のメッセージから、実際に保存すべき本文だけを
    抽出する。
    """
    for prefix in _APPEND_PREFIXES:
        if prefix in message:
            return message.replace(prefix, "", 1).strip()

    start_idx = None

    for marker in _APPEND_START_MARKERS:
        idx = message.find(marker)
        if idx != -1 and (start_idx is None or idx < start_idx):
            start_idx = idx + len(marker)

    remainder = message[start_idx:] if start_idx is not None else message

    end_idx = None

    for marker in _APPEND_END_MARKERS:
        idx = remainder.find(marker)
        if idx != -1 and (end_idx is None or idx < end_idx):
            end_idx = idx

    content = remainder[:end_idx] if end_idx is not None else remainder

    return content.strip()


def handle_sheets_message(
    message: str,
    user_id: str,
    client: GoogleSheetsClient,
):
    """Google Sheets request handler."""

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
    if _is_ai_analysis_request(message):
        rows = client.read_rows("A:Z")
        reply_text = generate_ai_sheet_reply(message, rows)

        return {
            "text": reply_text,
            "rows": rows,
            "success": True,
        }

    # Read
    if _is_read_request(message):
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
        content = _extract_append_content(message)

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

    # AI Analysis fallback: after all explicit operations above, treat a
    # natural-language Sheets question as an analysis request. Keep a bare
    # Sheets mention unchanged so it does not trigger an unnecessary AI call.
    if not _GENERIC_SHEET_MENTION_ONLY_PATTERN.fullmatch(message.strip()):
        rows = client.read_rows("A:Z")
        reply_text = generate_ai_sheet_reply(message, rows)

        return {
            "text": reply_text,
            "rows": rows,
            "success": True,
        }

    return None
