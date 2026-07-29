import ast
import tempfile
import subprocess


def validate_python_code(code):

    try:
        ast.parse(code)
        return {
            "ok": True,
            "message": "Python syntax OK"
        }

    except SyntaxError as e:
        return {
            "ok": False,
            "message": f"Syntax Error: {e}"
        }


def review_patch(patch):

    result = []

    result.append(
        "🔎 Patch Validator"
    )

    # 危険パターン確認
    if "except Exception" in patch:
        result.append(
            "⚠️ except位置を確認してください"
        )

    if "def " in patch:
        result.append(
            "⚠️ 関数変更を含みます"
        )

    if "+ " in patch or "- " in patch:
        result.append(
            "✅ diff形式を検出しました"
        )

    else:
        result.append(
            "⚠️ diff形式ではありません"
        )


    result.append(
        "自動適用はまだ無効です"
    )

    return "\n".join(result)
