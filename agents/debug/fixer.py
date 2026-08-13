def generate_fix_suggestion(error_info: dict) -> str:
    """
    エラー情報から修正案を生成する
    """

    error_type = error_info.get("error_type")
    file = error_info.get("file")
    line = error_info.get("line")
    message = error_info.get("message")
    file_hint = error_info.get("file_hint")

    # tracebackが認識できず、自然言語から対象ファイルだけ認識できた場合
    if error_type is None and file_hint:
        return f"""
【AI Debug Agent 修正提案】

■ 対象ファイル
{file_hint}

■ 状態
tracebackが見つからなかったため、修正案は生成できません。

■ 次のアクション
{file_hint} のエラーメッセージ・tracebackを貼り付けて再度お送りください。
"""

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

    elif error_type == "AttributeError":
        result += """
原因:
Noneや想定外の型のオブジェクトに対して属性・メソッドを呼び出しています。

修正案:
- 呼び出し前にNoneチェックを追加
- hasattr()による安全な属性確認を追加
- 該当オブジェクトの生成・取得処理を確認
"""

    elif error_type == "ModuleNotFoundError":
        result += """
原因:
Pythonが指定されたモジュールを読み込めません。

修正案:

- エラーメッセージから対象モジュール名を確認
- import文のモジュール名・パスを確認
- 自作モジュールの場合は対象ファイルの存在を確認
- 外部パッケージの場合はインストール状況を確認
- requirements.txtの依存関係を確認

注意:
対象コードを確認する前にimport文を削除したり、
存在しないパッケージを追加したりしないでください。
"""

    elif error_type == "NameError":
        result += """
原因:
変数・関数が未定義のまま参照されている、またはスペルミス・import漏れです。

修正案:
- 変数名・関数名のスペルを確認
- 定義順序・スコープを確認
- 必要なimport文を追加
"""

    else:
        result += """
詳細ログを確認して修正箇所を特定してください。
"""

    return result
