"""Bounded ideation agent contract for the distributed AI loop.

The idea agent is intentionally permissive about creativity: unusual, assumption-
breaking proposals are preserved for review. Safety is enforced at execution
boundaries, not by making ideation conservative.
"""
from __future__ import annotations

from dataclasses import dataclass
from .multi_agent import AgentRole, AgentTask

_MAX_IDEAS = 5
_MAX_CHARS = 4000


@dataclass(frozen=True)
class Idea:
    idea_id: str
    title: str
    rationale: str
    next_step: str
    task: AgentTask
    style: str = "unknown"
    novelty: int = 0
    positive_impact: str = ""
    safety_boundary: str = ""


class IdeaAgent:
    """Generate bounded, diverse, reviewable ideas without executing them."""

    role = AgentRole.IDEA

    def propose(
        self,
        focus: str,
        *,
        context: tuple[str, ...] = (),
        limit: int = _MAX_IDEAS,
    ) -> tuple[Idea, ...]:
        focus = focus.strip()
        if not focus:
            raise ValueError("focus is required")
        if len(focus) > _MAX_CHARS:
            raise ValueError("focus exceeds 4000 characters")
        if not 1 <= limit <= _MAX_IDEAS:
            raise ValueError("limit must be between 1 and 5")

        clean_context = tuple(item.strip() for item in context if item.strip())[:8]
        joined = "; ".join(clean_context)
        suffix = f" Context: {joined}." if joined else ""
        templates = (
            ("reframe", 3, "前提を一つ反転して別の設計条件として捉え直す",
             "既存の前提を一つ外して比較案を作る",
             "他AIに別の問題設定を与え、盲点を減らす"),
            ("recombine", 4, "異なるAIや機能を意外な組合せにして新しい用途を作る",
             "二つ以上の既存能力を共通イベント契約で接続する",
             "他AIの能力を横断的に再利用し、新しい協調方法を生む"),
            ("specialize", 2, "専門AIとして責務を極端に狭く切り出して精度を上げる",
             "責務・入力・出力・権限を最小契約にする",
             "他AIの負担を減らし、相互チェックを明確にする"),
            ("architecture-leap", 5, "現在のアーキテクチャを当然とせず、別の構造へ飛躍する",
             "現行設計とは独立した小さな実験プロトコルを作る",
             "他AIに新しい探索空間を提供する。ただし実行権限は増やさない"),
            ("constraint", 3, "無料・安全・停止可能という制約を逆に発想の起点にする",
             "無料経路とfail-closed境界を先に定義して案を具体化する",
             "他AIが安全性を保ったまま創造的に改善できる余地を増やす"),
        )
        ideas: list[Idea] = []
        for index, (style, novelty, rationale, next_step, impact) in enumerate(templates[:limit], 1):
            task = AgentTask(
                task_id=f"idea-{style}-{index}",
                role=AgentRole.IDEA,
                instruction=(
                    "発想候補のみ作成。実装・実行・マージ・デプロイは禁止。 No implementation, execution, merge, deploy."
                    "奇抜・非典型・前提破壊という理由だけで候補を捨てない。"
                    "ただし有害な実行方法や権限拡大は提案しない。"
                    f" Focus: {focus}{suffix}"
                ),
                resources=frozenset({"idea-proposals"}),
            )
            ideas.append(Idea(
                idea_id=f"{style}-{index}",
                title=f"{style}: {focus}",
                rationale=rationale,
                next_step=next_step,
                task=task,
                style=style,
                novelty=novelty,
                positive_impact=impact,
                safety_boundary="発想は保存するが、実行時はSafety Gateを必須とする",
            ))
        return tuple(ideas)


__all__ = ["Idea", "IdeaAgent"]
