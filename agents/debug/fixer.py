def generate_fix_suggestion(error_info: dict) -> str:
    """
    エラー情報から修正案を生成する
    """

    error_type = error_info.get("error_type")
    file = error_info.get("file")
    line = error_info.get("line")
    message = error_info.get("message")

    result = f"""
【AI Debug Agent 修正提案】

■ 対象ファイル
{file}

■ 行番号
{line}

■ エラー
{error_type}
{message}

■ 修正案
"""

    if error_type == "KeyError":
        result += """
原因:
存在しないキーを直接参照しています。

修正例:

修正前:
data["user_id"]

修正後:
data.get("user_id")

理由:
キーが存在しない場合でも安全に処理できます。
"""

    elif error_type == "TypeError":
        result += """
原因:
想定していない型のデータが渡されています。

修正案:
- 型チェックを追加
- Noneチェックを追加
"""

    elif error_type == "ValueError":
        result += """
原因:
値の形式が期待値と異なります。

修正案:
- 入力値検証を追加
- 変換処理を確認
"""

    else:
        result += """
詳細ログを確認して修正箇所を特定してください。
"""

    return result
