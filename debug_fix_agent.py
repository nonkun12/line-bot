from github_client import get_github_file
from render_client import get_render_logs
from code_analyzer import find_relevant_code
from debug_patch_agent import generate_patch
from debug_agent import run_debug_agent
from patch_validator import review_patch
from change_detector import detect_change_needed


def run_debug_fix_agent(error_text=""):

    try:

        # 原因解析
        analysis = run_debug_agent(error_text)

        # Renderログ取得
        logs = get_render_logs()

        # GitHubコード取得
        code = get_github_file("app.py")

        # 関連コード抽出
        relevant_code = find_relevant_code(
            code,
            logs
        )

        # 修正diff生成
        patch = generate_patch(
            analysis,
            relevant_code
        )

        # Patch安全確認
        validation = review_patch(
            patch
        )

        # 変更必要性確認
        change_check = detect_change_needed(
            relevant_code,
            patch
        )


        return f"""
🔧 AI Debug Fix Agent

【原因解析】

{analysis}


【修正提案】

{patch}


【安全チェック】

{validation}


【変更必要性チェック】

{change_check}


※ 自動適用はまだ無効です。
"""

    except Exception as e:

        return f"""
🔧 AI Debug Fix Agent

解析エラー:

{e}
"""
