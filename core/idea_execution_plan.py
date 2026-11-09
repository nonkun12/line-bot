"""Recurring execution plans proposed by IDEA and gated by Orca.

A plan describes what should happen and when. It is not a scheduler and cannot
activate workflows, grant permissions, or bypass existing task approval gates.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re


class PlanCadence(str, Enum):
    ONCE = "once"
    DAILY = "daily"
    WEEKLY = "weekly"


class PlanExecutionMode(str, Enum):
    REVIEW_ONLY = "review_only"
    AUTO_RUN_SAFE_STEPS = "auto_run_safe_steps"


@dataclass(frozen=True)
class RecurringPlanStep:
    step_id: str
    owner: str
    instruction: str
    output: str
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class IdeaExecutionPlan:
    plan_id: str
    title: str
    rationale: str
    cadence: PlanCadence
    timezone: str
    time_window: str
    execution_mode: PlanExecutionMode
    steps: tuple[RecurringPlanStep, ...]
    success_criteria: tuple[str, ...]
    idempotency_scope: str
    human_approval_required_for: tuple[str, ...]
    status: str = "PROPOSED"


def validate_plan(plan: IdeaExecutionPlan) -> None:
    """Fail closed on incomplete or unsafe recurring plans."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,79}", plan.plan_id):
        raise ValueError("invalid plan_id")
    if not plan.title.strip() or not plan.rationale.strip():
        raise ValueError("title and rationale are required")
    if plan.timezone != "Asia/Tokyo":
        raise ValueError("timezone must be explicit; only Asia/Tokyo is currently supported")
    if not re.fullmatch(r"(morning|afternoon|evening|HH:MM)", plan.time_window):
        raise ValueError("time_window must be morning, afternoon, evening, or HH:MM")
    if not plan.steps or len(plan.steps) > 8:
        raise ValueError("plan must contain 1 to 8 steps")
    if not plan.success_criteria or not plan.idempotency_scope:
        raise ValueError("success criteria and idempotency scope are required")

    ids = {step.step_id for step in plan.steps}
    if len(ids) != len(plan.steps):
        raise ValueError("duplicate step_id")
    for step in plan.steps:
        if not step.step_id.strip() or not step.owner.strip() or not step.instruction.strip() or not step.output.strip():
            raise ValueError("every step needs an id, owner, instruction, and output")
        if any(dependency not in ids or dependency == step.step_id for dependency in step.depends_on):
            raise ValueError("step dependency is missing or self-referential")

    if plan.execution_mode is PlanExecutionMode.AUTO_RUN_SAFE_STEPS:
        if not plan.human_approval_required_for:
            raise ValueError("auto-run plans must declare human approval boundaries")
        if plan.status != "PROPOSED":
            raise ValueError("new plans must remain PROPOSED until Orca approval")
    elif plan.execution_mode is not PlanExecutionMode.REVIEW_ONLY:
        raise ValueError("unknown execution mode")


def core_vocabulary_daily_plan() -> IdeaExecutionPlan:
    """Reference plan: propose and quality-check vocabulary every morning.

    This is a proposal only. It does not schedule a workflow or change the
    approved vocabulary registry.
    """
    plan = IdeaExecutionPlan(
        plan_id="core-vocabulary-daily-quality",
        title="コア英単語の毎朝追加候補・品質改善サイクル",
        rationale=(
            "語彙を少しずつ継続追加し、重複・誤訳・不自然な例文を防ぎながら"
            "学習対象の品質を上げる"
        ),
        cadence=PlanCadence.DAILY,
        timezone="Asia/Tokyo",
        time_window="morning",
        execution_mode=PlanExecutionMode.AUTO_RUN_SAFE_STEPS,
        steps=(
            RecurringPlanStep(
                "select", "IDEA",
                "既存語彙、過去候補、学習履歴を参照し、追加価値の高い候補を選ぶ",
                "重複確認済みの候補語と選定理由",
            ),
            RecurringPlanStep(
                "draft", "English Learning AI",
                "候補語ごとに核心イメージ、品詞、自然な例文、正確な和訳、関連語を作成する",
                "構造化された語彙候補",
                ("select",),
            ),
            RecurringPlanStep(
                "verify", "Independent reviewer / REA",
                "意味・品詞・語法・例文の自然さ・和訳の完全性・既存語との重複を検証する",
                "PASS / REVISE / BLOCKEDと根拠",
                ("draft",),
            ),
            RecurringPlanStep(
                "stage", "Orca",
                "PASS候補のみを追加候補領域に記録し、出典・検証結果・重複キーを保存する",
                "登録待ち候補と証拠",
                ("verify",),
            ),
            RecurringPlanStep(
                "learn", "English Learning AI",
                "登録済み学習項目から復習問題を作成し、学習者の回答結果を次回選定に返す",
                "復習セットと品質フィードバック",
                ("stage",),
            ),
        ),
        success_criteria=(
            "重複語を追加しない",
            "全候補に品詞・核心イメージ・自然な例文・意味を保った和訳がある",
            "独立レビューでPASSした候補だけを登録待ち領域に置く",
            "失敗・修正理由を次回の選定と品質検証に反映する",
        ),
        idempotency_scope="daily-date + normalized-headword",
        human_approval_required_for=(
            "approved vocabulary registryへの採用",
            "既存語彙の編集・削除",
            "学習者の学習履歴の変更",
            "スケジュール・権限・ワークフローの有効化や変更",
        ),
    )
    validate_plan(plan)
    return plan


__all__ = [
    "IdeaExecutionPlan",
    "PlanCadence",
    "PlanExecutionMode",
    "RecurringPlanStep",
    "core_vocabulary_daily_plan",
    "validate_plan",
]
