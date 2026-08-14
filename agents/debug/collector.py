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


def _has_traceback(text: str) -> bool:
    return "traceback" in (text or "").lower()


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

    # Error type
    match = _EXCEPTION_PATTERN.search(parse_text)

    if match:
        result["error_type"] = match.group(1)


    # file name
    match = re.search(
        r'File "([^"]+)"',
        parse_text
    )

    if match:
        result["file"] = match.group(1)


    # line number
    match = re.search(
        r"line (\d+)",
        parse_text
    )

    if match:
        result["line"] = int(match.group(1))


    # message
    lines = parse_text.strip().splitlines()

    if lines:
        result["message"] = lines[-1]


    # KeyError専用
    if result["error_type"] == "KeyError":

        key_match = re.search(
            r"KeyError:\s*['\"]?([^'\"]+)['\"]?",
            parse_text
        )

        if key_match:
            result["key"] = key_match.group(1)


    return result
