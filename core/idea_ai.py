"""Bounded, multi-domain ideation for the distributed AI loop.

IDEA explores product, architecture, agent collaboration, learning, and
reliability opportunities. It preserves unconventional candidates for review;
execution authority remains outside this module.
"""
from __future__ import annotations

from dataclasses import dataclass

from .multi_agent import AgentRole, AgentTask

_MAX_IDEAS = 5
_MAX_CHARS = 4000
_MAX_CONTEXT_ITEMS = 8


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
    domain: str = "general"
    assumption_to_test: str = ""
    success_signal: str = ""


# The tracks intentionally span different kinds of value, not just code changes.
_IDEA_TRACKS = (
    {
        "style": "reframe", "domain": "product-and-user-value", "novelty": 3,
        "title": "利用者価値の再定義",
        "rationale": "利用者が本当に解決したい課題から逆算し、既存機能の前提を問い直す",
        "next_step": "現状の利用手順と摩擦を列挙し、最小の代替体験を比較する",
        "impact": "機能追加だけに偏らず、使いやすさと成果を改善する",
        "assumption": "現在の機能分割が利用者の目的に最適とは限らない",
        "signal": "手順数・待ち時間・未完了率のいずれかが改善する",
    },
    {
        "style": "recombine", "domain": "cross-agent-collaboration", "novelty": 4,
        "title": "AI横断協調の発明",
        "rationale": "Orca、REA、専門AI、アイデアAIの異なる強みを組み合わせる",
        "next_step": "二つ以上のAI間で共有できる入力・成果物・証拠契約を設計する",
        "impact": "単独AIでは難しい分析・発想・検証の分業を可能にする",
        "assumption": "現在の逐次的な受け渡し以外にも有効な協調方式がある",
        "signal": "重複作業が減り、独立レビュー可能な証拠付き成果が増える",
    },
    {
        "style": "specialize", "domain": "learning-and-quality",
        "novelty": 2, "title": "学習・品質改善の専門化",
        "rationale": "失敗、修正、合格例から再利用可能な知識と検証課題を抽出する",
        "next_step": "誤りの分類、回帰テスト、復習候補を別々の成果物として提案する",
        "impact": "同じ失敗の再発を抑え、英語学習など継続領域の品質を高める",
        "assumption": "結果だけでなく誤りの原因を蓄積すれば改善効率が上がる",
        "signal": "同種の失敗率が下がり、検証済み学習項目が増える",
    },
    {
        "style": "architecture-leap", "domain": "new-capabilities",
        "novelty": 5, "title": "新能力・新構造の探索",
        "rationale": "現在の設計を前提にせず、低コストな新機能や異なる構造を探索する",
        "next_step": "既存構造と独立した小さな概念実証を設計し、比較条件を明示する",
        "impact": "将来の選択肢を増やし、既存方式に閉じた改善を避ける",
        "assumption": "現在の技術選択が最良とは限らず、別方式に利点がある",
        "signal": "再現可能な比較結果と採否判断の根拠が得られる",
    },
    {
        "style": "constraint", "domain": "reliability-and-efficiency",
        "novelty": 3, "title": "安全性・効率・継続性の両立",
        "rationale": "無料・ローカル優先・停止可能・fail-closedを制約ではなく設計資産にする",
        "next_step": "失敗時の停止点、再開条件、コスト、手動介入数を測定可能にする",
        "impact": "無駄な再試行や手作業を減らし、Mac不在時も安全に継続する",
        "assumption": "安全境界を明確にすれば自律性と効率を同時に高められる",
        "signal": "手動介入数・再試行回数が減り、誤実行ゼロを維持する",
    },
)


class IdeaAgent:
    """Generate diverse, actionable proposals without executing them."""

    role = AgentRole.IDEA

    def propose(
        self,
        focus: str,
        *,
        context: tuple[str, ...] = (),
        limit: int = _MAX_IDEAS,
    ) -> tuple[Idea, ...]:
        if not isinstance(focus, str):
            raise TypeError("focus must be a string")
        focus = focus.strip()
        if not focus:
            raise ValueError("focus is required")
        if len(focus) > _MAX_CHARS:
            raise ValueError("focus exceeds 4000 characters")
        if not 1 <= limit <= _MAX_IDEAS:
            raise ValueError("limit must be between 1 and 5")
        if not isinstance(context, tuple) or any(not isinstance(item, str) for item in context):
            raise TypeError("context must be a tuple of strings")

        clean_context = tuple(item.strip()[:500] for item in context if item.strip())[:_MAX_CONTEXT_ITEMS]
        context_text = "; ".join(clean_context)
        ideas: list[Idea] = []

        for index, track in enumerate(_IDEA_TRACKS[:limit], 1):
            style = track["style"]
            task = AgentTask(
                task_id=f"idea-{style}-{index}",
                role=AgentRole.IDEA,
                instruction=(
                    "提案・仮説・検証方法のみを作成する。実装・実行・マージ・デプロイは禁止。"
                    "奇抜・非典型・前提破壊という理由だけで候補を捨てない。"
                    "危険な実行方法、権限拡大、承認やHOLDの自己解除は提案しない。"
                    f" Focus: {focus}. Domain: {track['domain']}."
                    f" Context: {context_text}"
                ),
                resources=frozenset({"idea-proposals"}),
            )
            ideas.append(Idea(
                idea_id=f"{style}-{index}",
                title=f"{track['title']}: {focus}",
                rationale=track["rationale"],
                next_step=track["next_step"],
                task=task,
                style=style,
                novelty=track["novelty"],
                positive_impact=track["impact"],
                safety_boundary="発想は保存するが、実行時は独立したSafety Gateと明示承認を必須とする",
                domain=track["domain"],
                assumption_to_test=track["assumption"],
                success_signal=track["signal"],
            ))
        return tuple(ideas)


__all__ = ["Idea", "IdeaAgent"]
