"""
Google Sheets Agent intent detection
"""

def is_sheets_intent(message: str) -> bool:
    if not message:
        return False

    keywords = [
        "スプレッドシート",
        "Google Sheets",
        "Googleスプレッドシート",
        "シートに記録",
        "シートに追加",
        "シートを見て",
        "シートを読んで",
        "シートから検索",
        "シートを検索",
    ]

    if any(keyword in message for keyword in keywords):
        return True

    if "シート" in message and "削除" in message:
        return True

    # 「シートの内容を分析して」「シートから重要な予定を教えて」のような
    # 自然文でのAI分析リクエストも、シートに関する言及があれば
    # Sheets Agentへルーティングする(実際の分析要否の判断はHandler側で行う)。
    if "シート" in message:
        return True

    return False
