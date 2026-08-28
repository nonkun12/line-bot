import os
import shutil
import subprocess
from github_client import get_github_file
from render_client import get_render_logs
from ai_client import generate_chat_completion
from fix_generator import generate_patch
from patch_validator import review_patch, calculate_patch_safety_score
from patch_extractor import extract_diff
from code_analyzer import find_relevant_code, localize_fault, extract_context
from patch_applier import apply_patch, check_patch


def run_debug_agent(error_text=""):

    try:
        # Render本番ログ取得
        logs = get_render_logs()

        # GitHubコード取得
        code = get_github_file("app.py")

        # エラー関連コード抽出
        relevant_code = find_relevant_code(code, logs)

        # Fault Localization による最小コンテキスト抽出
        fault_info = localize_fault(logs)
        if fault_info and (fault_info.get("function") or fault_info.get("line")):
            localized_context = extract_context(
                code,
                function_name=fault_info.get("function"),
                line_number=fault_info.get("line"),
                padding=20
            )
            if localized_context:
                relevant_code = localized_context

        prompt = f"""
あなたはAIデバッグエージェントです。

本番環境(Render)で発生している問題を解析してください。
ログ内のERROR、Exception、HTTPエラーを最優先してください。推測ではなくログに存在する事実を使ってください。

Renderログ:
{logs[-8000:]}

ユーザー入力:
{error_text}

対象コード(app.py):
{relevant_code[:12000]}

回答形式:

1. 原因
2. 該当箇所
3. 修正方法
4. テスト方法
"""

        response = generate_chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": "あなたはシニアPythonデバッグエンジニアです。必ずログに存在する事実だけを書いてください。ログにない設定や環境変数を推測しないでください。原因不明の場合は原因未確定と書いてください。ERROR、Exception、Tracebackを最優先してください。",
                    "content": prompt
                }
            ],
            temperature=0.0,
            max_tokens=1024
        )

        analysis = response.choices[0].message.content

        fix_response = generate_chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": """
あなたは修正パッチ生成専用AIです。

既存コードを壊さない修正担当です。

出力規則:

許可される出力:
unified diff形式のみ

必ず以下の形式:
--- app.py
+++ app.py.fixed
@@ ...

ルール:
1. 変更可能なのは指定関数のみ
2. import変更禁止
3. 他関数変更禁止
4. 原因に直接関係する部分だけ修正する
5. ファイル全体を出力しない
6. 修正対象部分だけ返す
7. 変更20行以内

禁止事項:
1. 説明文禁止（「原因:」「修正理由:」「テスト方法:」「解説:」など一切の文章を出力しない）
2. Markdown記法禁止（```python などのコードブロック記号を出力しない）
3. Markdown装飾禁止
"""
                },
                {
                    "role": "user",
                    "content": f"""
原因分析:

{analysis}

対象コード:

{relevant_code}
"""
                }
            ],
            temperature=0.0,
            max_tokens=3000
        )

        fixed_code = fix_response.choices[0].message.content

        patch = generate_patch(
            relevant_code,
            fixed_code,
            "app.py"
        )

        target_func = fault_info.get("function") if fault_info else None

        validation = review_patch(
            patch,
            target_function=target_func
        )

        safety = calculate_patch_safety_score(
            patch,
            target_function=target_func
        )

        status_text = "✅ 安全性高" if safety["safe"] else "⚠️ 手動確認が必要"
        reasons_formatted = "\n".join([f"- {r}" for r in safety["reasons"]])

        safety_output = f"""Score: {safety['score']}/100

状態:
{status_text}

理由:
{reasons_formatted}"""

        # Auto Apply 条件チェック (全条件必須)
        check_apply = check_patch(patch, filename="app.py")
        can_auto_apply = (
            safety["score"] >= 90 and
            "自動適用禁止" not in validation and
            "import変更なし" in safety["reasons"] and
            "Markdown混入なし" in safety["reasons"] and
            any("変更範囲以内" in r for r in safety["reasons"]) and
            check_apply["ok"]
        )

        auto_apply_output = ""
        if can_auto_apply:
            apply_res = apply_patch(patch, filename="app.py")
            if apply_res["ok"]:
                # pytest 実行検証
                DEBUG_AGENT_TEST_TIMEOUT = float(os.environ.get("DEBUG_AGENT_TEST_TIMEOUT", "30.0"))
                try:
                    test_proc = subprocess.run(
                        ["arch", "-arm64", "venv/bin/pytest"],
                        capture_output=True,
                        text=True,
                        timeout=DEBUG_AGENT_TEST_TIMEOUT,
                    )
                except subprocess.TimeoutExpired as e:
                    class _TimedOutTestProc:
                        returncode = 1
                        stdout = e.stdout or ""
                        stderr = (e.stderr or "") + f"\n[DEBUG_AGENT] pytest timed out after {DEBUG_AGENT_TEST_TIMEOUT}s"
                    test_proc = _TimedOutTestProc()
                if test_proc.returncode == 0:
                    auto_apply_output = f"""

【Auto Apply】
状態:
✅ Auto Apply成功

適用結果:
{apply_res['message']}

Test:
全テスト通過 (pytest PASS)"""
                else:
                    # テスト失敗時ロールバック
                    if os.path.exists("app.py.before_auto_apply"):
                        shutil.copyfile("app.py.before_auto_apply", "app.py")
                    auto_apply_output = f"""

【Auto Apply】
状態:
⚠️ 自動適用キャンセル (テスト失敗のためロールバック完了)

理由:
pytest失敗"""
            else:
                auto_apply_output = f"""

【Auto Apply】
状態:
⚠️ 手動確認が必要

理由:
{apply_res['message']}"""
        else:
            auto_apply_output = f"""

【Auto Apply】
状態:
⚠️ 手動確認が必要

理由:
安全条件を満たしていません (Score: {safety['score']}/100)"""

        return f"""
🔍 AI Debug Agent

【原因解析】
{analysis}

【修正パッチ】
{patch}

【安全チェック】
{validation}

【Patch Safety】
{safety_output}{auto_apply_output}
"""

    except Exception as e:
        return f"""
🔍 AI Debug Agent

解析エラー:

{e}
"""


if __name__ == "__main__":
    print(run_debug_agent(
        """
ERROR:
set_reminder tool executed twice.

LOG:
set_reminder called id=176
set_reminder called id=177

Please analyze the cause.
"""
    ))
