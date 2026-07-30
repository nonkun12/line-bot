from .safety import SafetyGuard

__all__ = ["run_debug_agent"]


def run_debug_agent(error_text=""):
    """
    AI Debug Agent Phase 1 entry point.

    Phase 1:
    - read_only mode only
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
            "Phase 1では処理を受け付けられません。"
        )

    received = error_text.strip() if error_text else "(入力なし)"

    return (
        "🔍 AI Debug Agent\n\n"
        f"モード: {SafetyGuard.MODE} (読み取り専用)\n"
        "ファイル変更・git commit・git push・deployは行いません。\n\n"
        "【受付内容】\n"
        f"{received}\n\n"
        "Phase 1では解析の受付のみを行います。"
        "自動修正はPhase 2以降で対応予定です。"
    )