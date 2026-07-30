def analyze_error(error_text):
    """
    Phase 1.5 error analyzer
    read_only only
    """

    text = error_text.lower()

    print("DEBUG ANALYZER TEXT:", repr(text))

    if "modulenotfounderror" in text:
        return {
            "type": "Python Import Error",
            "cause": "必要なPythonパッケージが見つかりません。",
            "solution": "pip install で不足パッケージを追加してください。",
            "risk": "LOW"
        }

    if "keyerror" in text:
        return {
            "type": "Python Key Error",
            "cause": "辞書型データに存在しないキーを参照しています。",
            "solution": "キー存在確認（get()など）を追加してください。",
            "risk": "LOW"
        }

    if "typeerror" in text:
        return {
            "type": "Python Type Error",
            "cause": "異なる型のデータ操作が発生しています。",
            "solution": "変数の型確認と型変換を確認してください。",
            "risk": "LOW"
        }

    if "attributeerror" in text:
        return {
            "type": "Python Attribute Error",
            "cause": "存在しない属性やメソッドを呼び出しています。",
            "solution": "対象オブジェクトの型と属性を確認してください。",
            "risk": "LOW"
        }

    if "nameerror" in text:
        return {
            "type": "Python Name Error",
            "cause": "定義されていない変数や名前を使用しています。",
            "solution": "変数名とimport漏れを確認してください。",
            "risk": "LOW"
        }

    if "syntaxerror" in text:
        return {
            "type": "Python Syntax Error",
            "cause": "Python文法エラーがあります。",
            "solution": "エラー行周辺の記述を確認してください。",
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
