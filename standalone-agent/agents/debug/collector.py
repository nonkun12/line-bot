import re




# 自然言語文中の「拡張子付きファイル名らしきトークン」を検出するためのパターン。
# 例: "app.pyのエラーを確認して" -> "app.py"
_FILE_HINT_PATTERN = re.compile(
    r"(?P<path>[\w\-./]+\.[A-Za-z0-9]+)"
)

# Pythonの例外クラス名。末尾がError/Exceptionの一般的な例外に対応する。
# 日本語が直後に続く自然文でも検出できるよう、\bは使用しない。
_EXCEPTION_PATTERN = re.compile(
    r"([A-Za-z][A-Za-z0-9_]+(?:Error|Exception)|Exception)"
    r"(?![A-Za-z0-9_])"
)

# Python標準のtraceback出力の先頭に必ず現れるマーカー文字列。
# "traceback"という単語だけの自然文・通常ログとの誤判定を避けるため、
# 単語一致ではなくこの正規マーカーの有無で実tracebackかどうかを判定する。
_TRACEBACK_MARKER = "Traceback (most recent call last):"

# tracebackの末尾に現れる例外サマリ行(行頭が"ExceptionName: メッセージ"の形式)。
# tracebackブロックの終端を特定するために使用する。
_TRACEBACK_SUMMARY_LINE_PATTERN = re.compile(
    r"^[A-Za-z][A-Za-z0-9_]*(?:Error|Exception):.*$",
    re.MULTILINE,
)


def _has_traceback(text: str) -> bool:
    """
    Python標準tracebackの開始マーカーが含まれているかどうかを判定する。

    "traceback"という単語だけの自然文や通常ログ(例:
    「さっきのtracebackの件」「traceback機能は利用できません」)は
    Falseとなり、実際にPythonが出力したtraceback形式のみをTrueとする。
    """
    return _TRACEBACK_MARKER in (text or "")


def _isolate_traceback_block(text: str) -> str:
    """
    実tracebackの開始マーカーから例外サマリ行までを解析対象として切り出す。

    Renderログはtraceback発生後もDEBUG/INFOログが継続して出力されるため、
    解析範囲を絞らないとtraceback終了後の後続ログ行がfile/line/message/key
    の抽出に混入してしまう。この関数はtracebackマーカーが見つかった場合のみ、
    マーカーから例外サマリ行(行頭が"ExceptionName: ..."の行)までの範囲に
    テキストを限定する。

    tracebackマーカーが存在しない場合は元のテキストをそのまま返す。
    (自然文中の例外名だけを認識する既存の後方互換動作を維持するため)
    """
    if not text:
        return text

    start = text.find(_TRACEBACK_MARKER)

    if start == -1:
        return text

    summary_match = _TRACEBACK_SUMMARY_LINE_PATTERN.search(text, start)

    if summary_match:
        return text[start:summary_match.end()]

    # 例外サマリ行が見つからない(tracebackが途中で途切れている等)場合は
    # マーカー以降を解析対象とする。マーカーより前の内容(tracebackと無関係な
    # 先行ログ)は含めない。
    return text[start:]


def _extract_file_hint(text: str):
    """
    テキスト中から拡張子付きファイル名らしきトークンを1つ抽出する。
    見つからない場合は None を返す。
    """
    if not text:
        return None

    match = _FILE_HINT_PATTERN.search(text)

    if not match:
        return None

    return match.group("path")

def collect_error(error_text: str, log_text: str | None = None) -> dict:
    """
    tracebackやログ文字列から基本情報を抽出する。

    error_textだけを渡す従来の呼び出しはそのまま利用できる。
    log_textにRenderログを渡した場合は、実際のtracebackを含むRenderログを
    最優先する。Renderログにtracebackがなければ、LINE本文に貼られた
    tracebackを次に利用し、最後にLINE本文中の例外名だけを認識する。
    """

    result = {
        "error_type": None,
        "file": None,
        "line": None,
        "message": None,
        "key": None,
        "raw": error_text,
        "file_hint": None,
        "source": "user_message",
        "has_traceback": False,
        "request_text": error_text,
    }

    request_text = error_text or ""
    render_logs = log_text or ""

    # 実ログのtracebackのみを優先する。APIキー未設定などのエラー文字列を
    # log_textとして受け取っても、tracebackがなければ解析対象にはしない。
    if _has_traceback(render_logs):
        parse_text = render_logs
        result["source"] = "render"
    elif _has_traceback(request_text):
        parse_text = request_text
    else:
        parse_text = request_text

    result["raw"] = parse_text if parse_text else error_text
    result["has_traceback"] = _has_traceback(parse_text)
    result["file_hint"] = _extract_file_hint(request_text)

    if not parse_text:
        return result

    # tracebackが見つかった場合は、tracebackブロック(開始マーカー〜例外サマリ行)
    # の範囲だけを以降の抽出対象にする。これにより、traceback終了後に続く
    # DEBUG/INFOログなどの後続ログ行がfile/line/message/keyへ混入しない。
    # tracebackが見つからない場合(自然文中の例外名検出など)は、
    # 既存の後方互換動作のためparse_text全体を対象とする。
    extract_text = _isolate_traceback_block(parse_text)

    # Error type
    match = _EXCEPTION_PATTERN.search(extract_text)

    if match:
        result["error_type"] = match.group(1)


    # file name
    match = re.search(
        r'File "([^"]+)"',
        extract_text
    )

    if match:
        result["file"] = match.group(1)


    # line number
    match = re.search(
        r"line (\d+)",
        extract_text
    )

    if match:
        result["line"] = int(match.group(1))


    # message
    lines = extract_text.strip().splitlines()

    if lines:
        result["message"] = lines[-1]


    # KeyError専用
    if result["error_type"] == "KeyError":

        key_match = re.search(
            r"KeyError:\s*['\"]?([^'\"]+)['\"]?",
            extract_text
        )

        if key_match:
            result["key"] = key_match.group(1)


    return result
