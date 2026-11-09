import pytest

from core.idea_execution_plan import (
    PlanCadence,
    PlanExecutionMode,
    core_vocabulary_daily_plan,
    validate_plan,
)


def test_core_vocabulary_plan_is_daily_morning_tokyo_and_gated():
    plan = core_vocabulary_daily_plan()
    assert plan.cadence is PlanCadence.DAILY
    assert plan.timezone == "Asia/Tokyo"
    assert plan.time_window == "morning"
    assert plan.execution_mode is PlanExecutionMode.AUTO_RUN_SAFE_STEPS
    assert plan.status == "PROPOSED"
    assert [step.owner for step in plan.steps] == [
        "IDEA", "English Learning AI", "Independent reviewer / REA", "Orca",
        "English Learning AI",
    ]


def test_core_vocabulary_plan_preserves_human_approval_boundaries():
    plan = core_vocabulary_daily_plan()
    boundaries = " ".join(plan.human_approval_required_for)
    assert "approved vocabulary registry" in boundaries
    assert "学習履歴" in boundaries
    assert "ワークフロー" in boundaries


def test_core_vocabulary_plan_has_ordered_dependencies_and_quality_gates():
    plan = core_vocabulary_daily_plan()
    by_id = {step.step_id: step for step in plan.steps}
    assert by_id["draft"].depends_on == ("select",)
    assert by_id["verify"].depends_on == ("draft",)
    assert by_id["stage"].depends_on == ("verify",)
    assert by_id["learn"].depends_on == ("stage",)
    assert any("PASS" in criterion for criterion in plan.success_criteria)


def test_auto_run_plan_without_human_approval_boundaries_is_rejected():
    from dataclasses import replace

    plan = core_vocabulary_daily_plan()
    with pytest.raises(ValueError, match="approval boundaries"):
        validate_plan(replace(plan, human_approval_required_for=()))


def test_plan_rejects_unknown_timezone_and_invalid_dependencies():
    from dataclasses import replace

    plan = core_vocabulary_daily_plan()
    with pytest.raises(ValueError, match="timezone"):
        validate_plan(replace(plan, timezone="UTC"))
    broken_step = replace(plan.steps[0], depends_on=("missing",))
    with pytest.raises(ValueError, match="dependency"):
        validate_plan(replace(plan, steps=(broken_step, *plan.steps[1:])))
