def analyze_error(error_info: dict) -> str:
    """
    Collectorの結果から原因解析レポートを作成する
    """

    error_type = error_info.get("error_type")
    file = error_info.get("file")
    line = error_info.get("line")
    message = error_info.get("message")

    report = f"""
【AI Debug Agent 解析結果】

■ エラー種類
{error_type}

■ 発生場所
{file} line {line}

■ メッセージ
{message}

■ 原因推測
"""

    if error_type == "KeyError":
        report += """
辞書型データに存在しないキーを参照しています。

確認ポイント:
- dictionaryのキー名確認
- 外部入力データの存在確認
- get()による安全な取得
"""

    elif error_type == "TypeError":
        report += """
型が一致していない可能性があります。

確認ポイント:
- 変数の型確認
- Noneチェック
- 関数引数確認
"""

    elif error_type == "ValueError":
        report += """
値の形式が期待値と異なる可能性があります。

確認ポイント:
- 入力値チェック
- 変換処理確認
"""

    else:
        report += """
ログ詳細を追加確認する必要があります。
"""

    report += """

■ 修正方針
原因箇所を確認し、安全な修正を行ってください。
"""

    return report