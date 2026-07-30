def analyze_error(error_text):
    """
    Phase 1.5 basic error analyzer
    read_only only
    """

    text = error_text.lower()

    if "modulenotfounderror" in text:
        return {
            "type": "Python Import Error",
            "cause": "必要なPythonパッケージが見つかりません。",
            "solution": "pip install で不足パッケージを追加してください。",
            "risk": "LOW"
        }

    if "traceback" in text or "exception" in text:
        return {
            "type": "Python Exception",
            "cause": "Python実行中に例外が発生しています。",
            "solution": "Traceback末尾のエラー内容を確認してください。",
            "risk": "LOW"
        }

    return {
        "type": "Unknown Error",
        "cause": "エラー内容から原因を特定できませんでした。",
        "solution": "追加ログが必要です。",
        "risk": "LOW"
    }