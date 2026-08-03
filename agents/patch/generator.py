"""
Patch Agent Phase3: Patch候補生成処理

Fix Agentが生成したunified diff形式のpatch文字列を解析し、
実際のファイル変更・git操作を一切行わずに
PatchCandidate(変更候補)のリストを生成する。

重要:
- このモジュールはファイルの読み書きを行わない。
- git apply等のコマンド実行も行わない。
- 既存のPhase4a適用ロジック(agents/patch/apply.py, node.py内の
  patch_apply_node)とは完全に独立しており、一切変更しない。
"""

import math
import re
from typing import Optional

from agents.patch.schema import PatchCandidate


# safe_to_apply=Trueと判定するための最低確信度。
# Phase3では判定材料としてのみ使用し、実際の適用可否には使わない。
SAFE_CONFIDENCE_THRESHOLD = 0.7


def _split_diff_into_file_blocks(patch_text: str) -> list[str]:
    """
    unified diff文字列を、ファイル単位のブロックに分割する。

    "diff --git" ヘッダーを含むdiffの場合はその行を区切りとして使う。
    含まない場合(素のunified diff)は "--- " ヘッダーを区切りとして使う。

    ("diff --git" と "--- " の両方を区切りにすると、
    1ファイル分のdiffが誤って2ブロックに分割されてしまうため、
    どちらか一方のみを区切りとして使用する。)
    """

    if not patch_text or not patch_text.strip():
        return []

    lines = patch_text.splitlines()

    has_git_header = any(
        line.startswith("diff --git") for line in lines
    )

    split_prefix = "diff --git" if has_git_header else "--- "

    blocks: list[list[str]] = []
    current: list[str] = []

    for line in lines:
        if line.startswith(split_prefix) and current:
            blocks.append(current)
            current = [line]
        else:
            current.append(line)

    if current:
        blocks.append(current)

    return ["\n".join(block) for block in blocks]


def _extract_target_file(block: str) -> Optional[str]:
    """
    diffブロックから変更対象ファイル名を抽出する。
    """

    match = re.search(r"\+\+\+ b/(.+)", block)

    if match:
        return match.group(1).strip()

    match = re.search(r"--- a/(.+)", block)

    if match:
        return match.group(1).strip()

    return None


def _extract_before_after(block: str) -> tuple[str, str]:
    """
    diffブロックから削除行(before)・追加行(after)のみを抽出する。

    ヘッダー行("---" / "+++")はbefore/afterの対象から除外する。
    """

    before_lines: list[str] = []
    after_lines: list[str] = []

    for line in block.splitlines():
        if line.startswith(("---", "+++")):
            continue

        if line.startswith("-"):
            before_lines.append(line[1:])

        elif line.startswith("+"):
            after_lines.append(line[1:])

    return (
        "\n".join(before_lines),
        "\n".join(after_lines),
    )


def _calculate_confidence(fix_result: dict) -> float:
    """
    Fix Agentが示した confidence を 0.0〜1.0 に正規化して取得する。

    値が存在しない・数値に変換できない場合は 0.0 を返す
    (安全側に倒す)。
    """

    raw_confidence = fix_result.get("confidence", 0.0)

    try:
        confidence = float(raw_confidence)
    except (TypeError, ValueError):
        return 0.0

    if math.isnan(confidence):
        return 0.0

    if confidence < 0.0:
        return 0.0

    if confidence > 1.0:
        return 1.0

    return confidence


def _determine_safe_to_apply(
    fix_result: dict,
    confidence: float,
    target_file: Optional[str],
    before: str,
    after: str,
) -> bool:
    """
    Patch候補を(将来的に)自動適用しても安全と判断できるかを
    機械的に判定する。

    Phase3ではこの判定結果を候補への注釈情報として
    付与するのみであり、実際の適用処理には使用しない。
    """

    # 対象ファイルが特定できない候補は安全と判定しない
    if not target_file:
        return False

    # 追加行が存在しない、またはbefore/afterが同一(実質差分なし)の場合
    if not after or before == after:
        return False

    # Fix Agent自身がpatch検証NGとした場合
    if fix_result.get("patch_valid") is False:
        return False

    # 確信度が閾値以上であることを最終条件とする
    return confidence >= SAFE_CONFIDENCE_THRESHOLD


def generate_patch_candidates(fix_result: dict) -> list[PatchCandidate]:
    """
    Fix Agentの結果(FixResult相当のdict)からPatch候補のリストを生成する。

    Phase3の制約:
    - 実際のファイル変更・git操作は一切行わない
    - あくまで構造化されたPatch候補(PatchCandidate)のリストを返すのみ

    不正な入力(None・dict以外・patchがstr以外等)の場合は、
    例外を送出せず空リストを返す。
    """

    if not fix_result or not isinstance(fix_result, dict):
        return []

    patch_text = fix_result.get("patch", "")

    if not isinstance(patch_text, str):
        return []

    blocks = _split_diff_into_file_blocks(patch_text)

    reason = fix_result.get("summary") or "修正理由は生成されませんでした"

    if not isinstance(reason, str):
        reason = str(reason)

    confidence = _calculate_confidence(fix_result)

    candidates: list[PatchCandidate] = []

    for block in blocks:
        target_file = _extract_target_file(block)

        before, after = _extract_before_after(block)

        safe_to_apply = _determine_safe_to_apply(
            fix_result,
            confidence,
            target_file,
            before,
            after,
        )

        candidate: PatchCandidate = {
            "target_file": target_file or "unknown",
            "before": before,
            "after": after,
            "reason": reason,
            "confidence": confidence,
            "safe_to_apply": safe_to_apply,
        }

        candidates.append(candidate)

    return candidates
