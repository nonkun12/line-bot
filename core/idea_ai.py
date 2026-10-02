"""Bounded ideation agent contract for the distributed AI loop.

The idea agent proposes possibilities only. It has no repository mutation,
execution, merge, deploy, or permission-escalation capability.
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


class IdeaAgent:
    """Generate bounded, reviewable ideas without executing them."""

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
            ("reframe", "前提を一つ反転して別の設計条件として捉え直す", "既存の前提を一つ外して比較案を作る"),
            ("combine", "既存機能を異なる組合せにして新しい用途を作る", "対象機能を二つ選び共通イベント契約を設計する"),
            ("specialize", "専門AIとして責務を狭く切り出して精度を上げる", "責務・入力・出力・権限を契約にする"),
            ("future", "将来の利用形態から逆算して今の最小基盤を考える", "将来像から現在必要な最小インターフェースを抽出する"),
            ("constraint", "無料・安全・停止可能という制約を発想の起点にする", "無料経路とfail-closed境界を先に定義する"),
        )
        ideas: list[Idea] = []
        for index, (key, rationale, next_step) in enumerate(templates[:limit], 1):
            task = AgentTask(
                task_id=f"idea-{key}-{index}",
                role=AgentRole.IDEA,
                instruction=f"発想候補のみ作成。実装・実行・マージ・デプロイは禁止。Focus: {focus}{suffix}",
                resources=frozenset({"idea-proposals"}),
            )
            ideas.append(Idea(key, f"{key}: {focus}", rationale, next_step, task))
        return tuple(ideas)


__all__ = ["Idea", "IdeaAgent"]
