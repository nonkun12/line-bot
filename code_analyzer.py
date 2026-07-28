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
