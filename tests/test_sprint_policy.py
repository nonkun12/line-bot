from core.sprint_policy import assess_sprint_readiness


def _goal():
    return {
        "goal_id": "goal-sprint-test",
        "objective": "Complete a verified increment",
        "success_criteria": [
            {"id": "tests", "description": "Focused tests pass"},
            {"id": "review", "description": "Independent review passes"},
        ],
        "jobs": [
            {
                "id": "first-test", "criterion_id": "tests", "stage": "test",
                "instruction": "Run focused tests.",
                "allowed_paths": ["tests/test_sprint_policy.py"], "depends_on": [],
            },
            {
                "id": "second-review", "criterion_id": "review", "stage": "review",
                "instruction": "Review the test evidence.",
                "allowed_paths": ["docs/sprint-review.md"], "depends_on": ["first-test"],
            },
        ],
    }


def _grant():
    return {
        "grant_id": "grant-sprint-test", "goal_id": "goal-sprint-test",
        "active": True, "approved_by": "repository-owner",
        "expires_at": "2099-01-01T00:00:00Z",
        "auto_approve_registered_jobs": True, "max_jobs": 8,
        "allowed_stages": ["test", "review", "fix"],
        "allowed_path_prefixes": ["tests/", "docs/"],
        "auto_merge": False, "auto_deploy": False,
    }


def _candidate(**overrides):
    value = {
        "sprint_id": "sprint-001", "goal_id": "goal-sprint-test",
        "sequence": 1, "sprint_goal": "Verify one complete increment",
        "job_keys": ["first-test", "second-review"],
        "acceptance_criteria": ["tests", "review"], "max_jobs": 2,
    }
    value.update(overrides)
    return value


def test_readiness_reuses_goal_planner_and_returns_no_side_effect_permissions():
    result = assess_sprint_readiness(
        _goal(), _grant(), {"tests": "FAIL", "review": "FAIL"}, {}, _candidate()
    )
    assert result["decision"] == "READY"
    assert [job["id"] for job in result["jobs"]] == ["first-test", "second-review"]
    assert result["create_sprint"] is False
    assert result["create_job"] is False
    assert result["execute_job"] is False
    assert result["permissions"]["merge"] is False
    assert result["permissions"]["deploy"] is False


def test_readiness_holds_when_job_order_bypasses_goal_planner():
    result = assess_sprint_readiness(
        _goal(), _grant(), {"tests": "FAIL", "review": "FAIL"}, {},
        _candidate(job_keys=["second-review", "first-test"]),
    )
    assert result["decision"] == "HOLD"
    assert result["reason"] == "sprint_job_order_differs_from_goal_planner"


def test_readiness_holds_for_unregistered_or_empty_jobs():
    for keys in ([], ["not-registered"]):
        result = assess_sprint_readiness(
            _goal(), _grant(), {"tests": "FAIL", "review": "FAIL"}, {},
            _candidate(job_keys=keys),
        )
        assert result["decision"] == "HOLD"


def test_readiness_holds_when_acceptance_criteria_are_not_covered():
    result = assess_sprint_readiness(
        _goal(), _grant(), {"tests": "FAIL", "review": "FAIL"}, {},
        _candidate(job_keys=["first-test"]),
    )
    assert result["decision"] == "HOLD"
    assert result["reason"] == "sprint_jobs_do_not_cover_acceptance_criteria"


def test_readiness_holds_for_goal_mismatch_or_invalid_budget():
    mismatch = assess_sprint_readiness(
        _goal(), _grant(), {"tests": "FAIL", "review": "FAIL"}, {},
        _candidate(goal_id="another-goal"),
    )
    over_budget = assess_sprint_readiness(
        _goal(), _grant(), {"tests": "FAIL", "review": "FAIL"}, {},
        _candidate(max_jobs=11),
    )
    assert mismatch["reason"] == "sprint_goal_mismatch"
    assert over_budget["reason"] == "sprint_budget_invalid"


def test_readiness_holds_when_grant_is_missing():
    result = assess_sprint_readiness(
        _goal(), None, {"tests": "FAIL", "review": "FAIL"}, {}, _candidate()
    )
    assert result["decision"] == "HOLD"
    assert result["reason"] == "goal_planner_did_not_authorize_sprint_job"


def test_readiness_holds_when_grant_is_expired():
    grant = _grant()
    grant["expires_at"] = "2000-01-01T00:00:00Z"
    result = assess_sprint_readiness(
        _goal(), grant, {"tests": "FAIL", "review": "FAIL"}, {}, _candidate()
    )
    assert result["decision"] == "HOLD"
    assert result["reason"] == "goal_planner_did_not_authorize_sprint_job"


def test_readiness_holds_when_sprint_budget_exceeds_grant_budget():
    grant = _grant()
    grant["max_jobs"] = 1
    result = assess_sprint_readiness(
        _goal(), grant, {"tests": "FAIL", "review": "FAIL"}, {}, _candidate()
    )
    assert result["decision"] == "HOLD"
    assert result["reason"] == "goal_planner_did_not_authorize_sprint_job"
