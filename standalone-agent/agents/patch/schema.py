"""
Patch Agent Phase3: Schema定義

Fix Agentの提案内容から生成する
Patch候補(PatchCandidate)のデータ構造を定義する。

注意:
Phase3では「候補生成」のみを扱う。
実際のファイル変更・git操作を伴う適用ロジックは
agents/patch/apply.py (Phase4a) の責務であり、
このスキーマとは独立している。
"""

from typing import TypedDict


class PatchCandidate(TypedDict, total=False):
    """
    Patch候補1件分のデータ構造

    target_file:
        変更対象のファイルパス

    before:
        変更前のコード(unified diffの削除行から抽出)

    after:
        変更後のコード(unified diffの追加行から抽出)

    reason:
        この変更を提案する理由(Fix Agentのsummary等)

    confidence:
        Fix Agentが示した確信度(0.0〜1.0)

    safe_to_apply:
        機械的な判定に基づき、将来的に自動適用しても
        安全と判断できるかどうか。

        Phase3ではこの値を判定材料として算出するのみで、
        実際の適用可否判断・適用処理には使用しない。
    """

    target_file: str

    before: str

    after: str

    reason: str

    confidence: float

    safe_to_apply: bool
