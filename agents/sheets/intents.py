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

    return any(keyword in message for keyword in keywords)
