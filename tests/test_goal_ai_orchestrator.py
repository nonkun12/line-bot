import copy

import pytest

from core.goal_ai_orchestrator import (
    GoalPlanError,
    evaluate_goal_progress,
    validate_goal_plan,
)


def _plan():
    return {
        "schema_version": 1,
        "goal_id": "goal-line-ai",
        "goal": "LINEから安全に開発を指示し、結果を確認できるようにする",
        "max_parallel_jobs": 2,
        "jobs": [
            {
                "id": "inspect",
                "title": "現状調査",
                "instruction": "既存のルーティングとテストを調べる",
                "agent": "research",
                "depends_on": [],
                "allowed_paths": [],
                "approval_required": False,
            },
            {
                "id": "implement",
                "title": "安全な修正",
                "instruction": "承認済みの変更範囲だけを修正する",
                "agent": "development",
                "depends_on": ["inspect"],
                "allowed_paths": ["core/"],
                "approval_required": True,
            },
            {
                "id": "verify",
                "title": "検証",
                "instruction": "関連テストとREAを実行する",
                "agent": "test",
                "depends_on": ["implement"],
                "allowed_paths": [],
                "approval_required": False,
            },
            {
                "id": "report",
                "title": "成果報告",
                "instruction": "証拠と未解決事項を報告する",
                "agent": "report",
                "depends_on": ["verify"],
                "allowed_paths": [],
                "approval_required": False,
            },
        ],
    }


def test_validates_goal_plan_and_preserves_job_order():
    plan = validate_goal_plan(_plan())
    assert plan["goal_id"] == "goal-line-ai"
    assert [job["id"] for job in plan["jobs"]] == ["inspect", "implement", "verify", "report"]


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda p: p.update(extra=True), "goal_plan_schema_invalid"),
        (lambda p: p.update(max_parallel_jobs=True), "parallel_limit_invalid"),
        (lambda p: p["jobs"][1].update(allowed_paths=["../secrets"]), "allowed_paths_invalid"),
        (lambda p: p["jobs"][1].update(allowed_paths=[]), "development_job_requires_path_allowlist"),
        (lambda p: p["jobs"][0].update(depends_on=["missing"]), "job_dependency_unknown"),
        (lambda p: p["jobs"][0].update(depends_on=["report"]), "job_dependency_cycle"),
        (lambda p: p["jobs"][0].update(agent="shell"), "job_agent_invalid"),
        (lambda p: p["jobs"][0].update(approval_required=1), "approval_flag_invalid"),
    ],
)
def test_invalid_plans_fail_closed(mutate, reason):
    payload = _plan()
    mutate(payload)
    with pytest.raises(GoalPlanError, match=reason):
        validate_goal_plan(payload)


def test_goal_ai_returns_only_dependency_ready_jobs_with_parallel_cap():
    plan = _plan()
    result = evaluate_goal_progress(plan)
    assert result["status"] == "READY"
    assert result["ready_job_ids"] == ["inspect"]
    assert result["execution_authorized"] is False


def test_goal_ai_releases_next_job_only_after_dependency_completion():
    result = evaluate_goal_progress(_plan(), completed_job_ids=["inspect"])
    assert result["status"] == "READY"
    assert result["ready_job_ids"] == ["implement"]


def test_goal_ai_respects_parallel_limit():
    plan = _plan()
    plan["jobs"][1]["depends_on"] = []
    result = evaluate_goal_progress(plan, running_job_ids=["inspect"])
    assert result["status"] == "READY"
    assert result["ready_job_ids"] == ["implement"]


def test_goal_ai_holds_all_new_work_after_failed_or_blocked_job():
    for state_key in ("failed_job_ids", "blocked_job_ids"):
        result = evaluate_goal_progress(_plan(), **{state_key: ["inspect"]})
        assert result["status"] == "HOLD"
        assert result["ready_job_ids"] == []


def test_goal_ai_marks_complete_only_when_all_jobs_completed():
    result = evaluate_goal_progress(
        _plan(), completed_job_ids=["inspect", "implement", "verify", "report"]
    )
    assert result["status"] == "COMPLETE"
    assert result["ready_job_ids"] == []


def test_running_job_must_have_completed_dependencies():
    with pytest.raises(GoalPlanError, match="job_state_dependency_not_satisfied"):
        evaluate_goal_progress(_plan(), running_job_ids=["verify"])


def test_job_states_cannot_overlap_or_reference_unknown_jobs():
    with pytest.raises(GoalPlanError, match="job_states_overlap"):
        evaluate_goal_progress(_plan(), completed_job_ids=["inspect"], running_job_ids=["inspect"])
    with pytest.raises(GoalPlanError, match="completed_job_id_unknown"):
        evaluate_goal_progress(_plan(), completed_job_ids=["unknown"])
