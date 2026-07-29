import ast
import re


def find_relevant_code(code, logs):

    """
    ログから関連する関数名を推測して
    該当コード周辺を取得する
    """

    keywords = []

    # URLエンドポイントから関数名推測
    endpoint_map = {
        "/internal/push": "internal_push",
        "/internal/ai_report": "internal_ai_report"
    }

    for endpoint, func in endpoint_map.items():
        if endpoint in logs:
            keywords.append(func)


    # 関数名らしい文字を抽出
    funcs = re.findall(
        r"def\s+([a-zA-Z_][a-zA-Z0-9_]*)",
        code
    )

    # ログに含まれる関数を探す
    for func in funcs:
        if func in logs:
            keywords.append(func)

    # 見つからない場合は全体先頭
    if not keywords:
        return code[:5000]


    result = []

    lines = code.splitlines()

    for func in keywords:

        for i, line in enumerate(lines):

            if f"def {func}" in line:

                start = max(0, i - 5)
                end = min(len(lines), i + 60)

                result.extend(
                    lines[start:end]
                )

    return "\n".join(result)


def localize_fault(logs):
    """
    Python tracebackからエラー発生場所（ファイル、関数、行番号）を抽出する
    """
    pattern = r'File "([^"]+)", line (\d+), in ([a-zA-Z_][a-zA-Z0-9_]*)'
    matches = re.findall(pattern, logs)
    if not matches:
        return None

    last_match = matches[-1]
    return {
        "file": last_match[0],
        "line": int(last_match[1]),
        "function": last_match[2]
    }


def extract_function_by_name(code, function_name):
    """
    ASTを利用して指定関数のみ抽出する
    """
    try:
        tree = ast.parse(code)
        lines = code.splitlines()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
                start_line = node.lineno - 1
                end_line = getattr(node, 'end_lineno', start_line + 50)
                return "\n".join(lines[start_line:end_line])
    except Exception:
        pass
    return None


def extract_context(code, function_name=None, line_number=None, padding=20):
    """
    エラー行番号周辺または指定関数の最小コンテキストを取得する
    """
    lines = code.splitlines()

    # 1. 行番号が特定できている場合はエラー発生行の前後（Minimal Context）を優先
    if line_number is not None and 1 <= line_number <= len(lines):
        idx = line_number - 1
        start = max(0, idx - padding)
        end = min(len(lines), idx + padding + 1)
        return "\n".join(lines[start:end])

    # 2. 行番号がない場合は指定関数のAST抽出を試行
    if function_name:
        func_code = extract_function_by_name(code, function_name)
        if func_code:
            return func_code

        for i, line in enumerate(lines):
            if f"def {function_name}" in line:
                start = max(0, i - padding)
                end = min(len(lines), i + padding + 60)
                return "\n".join(lines[start:end])

    return None

