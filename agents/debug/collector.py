import re




# 自然言語文中の「拡張子付きファイル名らしきトークン」を検出するためのパターン。
# 例: "app.pyのエラーを確認して" -> "app.py"
_FILE_HINT_PATTERN = re.compile(
    r"(?P<path>[\w\-./]+\.[A-Za-z0-9]+)"
)


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

def collect_error(error_text: str) -> dict:
    """
    tracebackやログ文字列から基本情報を抽出する
    """

    result = {
        "error_type": None,
        "file": None,
        "line": None,
        "message": None,
        "key": None,
        "raw": error_text,
        "file_hint": None,
    }

    if not error_text:
        return result

    result["file_hint"] = _extract_file_hint(error_text)

    # Error type
    match = re.search(
        r"([A-Za-z]+Error|Exception):",
        error_text
    )

    if match:
        result["error_type"] = match.group(1)


    # file name
    match = re.search(
        r'File "([^"]+)"',
        error_text
    )

    if match:
        result["file"] = match.group(1)


    # line number
    match = re.search(
        r"line (\d+)",
        error_text
    )

    if match:
        result["line"] = int(match.group(1))


    # message
    lines = error_text.strip().splitlines()

    if lines:
        result["message"] = lines[-1]


    # KeyError専用
    if result["error_type"] == "KeyError":

        key_match = re.search(
            r"KeyError:\s*['\"]?([^'\"]+)['\"]?",
            error_text
        )

        if key_match:
            result["key"] = key_match.group(1)


    return result
