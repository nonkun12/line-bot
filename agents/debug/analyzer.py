def analyze_error(error_info: dict) -> str:
    """
    Collectorの結果から原因解析レポートを作成する
    """

    error_type = error_info.get("error_type")
    file = error_info.get("file")
    line = error_info.get("line")
    message = error_info.get("message")
    file_hint = error_info.get("file_hint")

    # tracebackが認識できず、自然言語から対象ファイルだけ認識できた場合
    if error_type is None and file_hint:
        return f"""
【AI Debug Agent 解析結果】

■ 対象ファイル
{file_hint}

■ 状態
tracebackが見つかりませんでした。

■ 原因推測
「{file_hint}」に関するエラーの確認を依頼されましたが、
実際のエラーメッセージ・tracebackがメッセージ内に含まれていないため、
自動解析ができませんでした。

■ 修正方針
{file_hint} を実行した際に発生したエラーメッセージ・tracebackを
そのまま貼り付けて再度お送りください。
"""

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

    elif error_type == "AttributeError":
        report += """
オブジェクトに存在しない属性・メソッドを参照している可能性があります。

確認ポイント:
- 変数がNoneになっていないか確認
- オブジェクトの型が想定通りか確認
- 属性名・メソッド名のタイプミス確認
"""

    elif error_type == "ModuleNotFoundError":
        report += """
Pythonが指定されたモジュールを読み込めていません。

確認ポイント:

- importしているモジュール名が正しいか確認
- プロジェクト内に対象モジュールが存在するか確認
- 自作モジュールの場合はファイル配置とimportパスを確認
- 外部パッケージの場合はインストール状況を確認
- requirements.txtに必要なパッケージが含まれているか確認
- ローカル環境とデプロイ環境の依存関係を確認
"""

    elif error_type == "NameError":
        report += """
定義されていない変数・関数を参照している可能性があります。

確認ポイント:
- 変数名・関数名のスペル確認
- import漏れの確認
- 変数のスコープ（定義位置）確認
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