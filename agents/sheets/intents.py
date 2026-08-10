"""
Google Sheets Agent intent detection
"""

def is_sheets_intent(message: str) -> bool:
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

    return False
