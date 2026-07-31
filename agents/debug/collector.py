import re


def collect_error(error_text: str) -> dict:
    """
    tracebackやログ文字列から基本情報を抽出する
    """

    result = {
        "error_type": None,
        "file": None,
        "line": None,
        "message": None,
        "raw": error_text,
    }

    if not error_text:
        return result

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

    return result