from .safety import SafetyGuard
from .analyzer import analyze_error

__all__ = ["run_debug_agent"]


def run_debug_agent(error_text=""):
    """
    AI Debug Agent Phase 1.5 entry point.

    Phase 1.5:
    - read_only mode only
    - analysis only
    - no file modification
    - no git commit
    - no git push
    - no deploy
    """

    if (
        SafetyGuard.MODE != "read_only"
        or SafetyGuard.can_modify_file()
        or SafetyGuard.can_git_commit()
        or SafetyGuard.can_git_push()
        or SafetyGuard.can_deploy()
    ):
        return (
            "🔍 AI Debug Agent\n\n"
            "安全設定が read_only ではないため、"
            "処理を受け付けられません。"
        )

    received = error_text.strip() if error_text else "(入力なし)"

    analysis = analyze_error(received)

    return (
        "🔍 AI Debug Agent\n\n"
        f"モード: {SafetyGuard.MODE} (読み取り専用)\n"
        "ファイル変更・git commit・git push・deployは行いません。\n\n"
        "【受付内容】\n"
        f"{received}\n\n"
        "【解析結果】\n"
        f"種類: {analysis['type']}\n"
        f"発生場所: {analysis.get('location', '不明')}\n"
        f"原因: {analysis['cause']}\n"
        f"対策: {analysis['solution']}\n"
        f"安全レベル: {analysis['risk']}\n\n"
        "※現在は解析・提案のみです。"
    )
