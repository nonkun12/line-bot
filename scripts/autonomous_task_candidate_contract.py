"""Shared instruction contract for review-only autonomous task candidates."""

def build_review_instruction(test_path: str, source_function: str, evidence: str) -> str:
    """Return the exact, bounded test-only instruction emitted and validated."""
    return (
        f"人手レビュー後に限り、{test_path} に {source_function} ({evidence}) の"
        "境界条件を検証する新しい回帰テストを1件追加してください。"
        "まず既存テストと間接カバレッジを確認し、重複する場合は変更せず理由を報告してください。"
        "既存テスト関数・assert・fixture・parametrize・classは変更、削除、改名、並べ替え禁止。"
        "ファイル末尾に新しいpytest test関数を1つだけ追記し、既存定義を一切変更しないでください。"
        "安全な追記ができなければ変更せず理由を報告してください。"
        "変更は指定テストファイル1つだけ。実装コード・workflow・catalog・stateは変更禁止。"
        "外部通信・シークレット参照・OS操作・マージ・デプロイは禁止。"
    )
