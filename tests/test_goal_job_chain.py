from scripts.goal_job_chain import MAX_AUTONOMOUS_JOBS_PER_GOAL, plan_next_job


def _goal():
    return {
        "goal_id": "goal-line-autonomy",
        "objective": "LINEから安全に開発指示を実行できる",
        "success_criteria": [
            {"id": "line-routing", "description": "開発指示と読み取り専用指示を区別する"},
            {"id": "safe-execution", "description": "テストとレビューの証拠を確認する"},
        ],
        "jobs": [
            {
                "id": "routing-tests", "criterion_id": "line-routing",
                "stage": "test", "instruction": "Add focused routing regression tests.",
                "allowed_paths": ["tests/test_task_routing_line_development.py"],
                "depends_on": [],
            },
            {
                "id": "safe-review", "criterion_id": "safe-execution",
                "stage": "review", "instruction": "Review evidence gates.",
                "allowed_paths": ["tests/test_creator_critic_diff_review.py"],
                "depends_on": ["routing-tests"],
            },
        ],
    }


def _grant():
    return {
        "grant_id": "grant-line-goal-001",
        "goal_id": "goal-line-autonomy",
        "active": True,
        "approved_by": "repository-owner",
        "expires_at": "2099-01-01T00:00:00Z",
        "auto_approve_registered_jobs": True,
        "max_jobs": 12,
        "allowed_stages": ["requirements", "design", "implementation", "test", "review", "fix", "verify"],
        "allowed_path_prefixes": ["tests/", "docs/", "agents/", "core/", "scripts/"],
        "auto_merge": False,
        "auto_deploy": False,
    }


def test_goal_planner_requires_only_one_goal_level_grant_for_safe_child_jobs():
    result = plan_next_job(
        _goal(), {"line-routing": "FAIL", "safe-execution": "FAIL"}, {},
        autonomy_grant=_grant(),
    )
    assert result["decision"] == "PROPOSE_CHILD_JOB"
    assert result["job"]["id"] == "routing-tests"
    assert result["approval_mode"] == "deterministic_low_risk_auto_approval"
    assert result["human_approval_required"] is False
    assert result["autonomy_grant_id"] == "grant-line-goal-001"
    assert result["remaining_job_budget"] == 11
    assert result["create_job"] is False
    assert result["execute_job"] is False
    assert result["permissions"]["merge"] is False
    assert result["permissions"]["deploy"] is False


def test_goal_planner_does_not_self_authorize_from_goal_payload():
    goal = _goal()
    goal["autonomy_policy"] = {"auto_approve_registered_jobs": True}
    result = plan_next_job(goal, {"line-routing": "FAIL", "safe-execution": "FAIL"}, {})
    assert result["decision"] == "HOLD"
    assert result["reason"] == "autonomy_policy_must_be_server_controlled"

    result = plan_next_job(_goal(), {"line-routing": "FAIL", "safe-execution": "FAIL"}, {})
    assert result["decision"] == "HOLD"
    assert result["approval_required_jobs"][0]["reason"] == "goal_autonomy_grant_required"


def test_goal_planner_rejects_invalid_or_mismatched_goal_grants():
    grant = _grant()
    grant["goal_id"] = "another-goal"
    result = plan_next_job(_goal(), {"line-routing": "FAIL", "safe-execution": "FAIL"}, {}, autonomy_grant=grant)
    assert result["decision"] == "HOLD"
    assert result["reason"] == "autonomy_grant_invalid_or_mismatched"


def test_goal_planner_waits_for_parent_job_before_child():
    result = plan_next_job(
        _goal(), {"line-routing": "PASS", "safe-execution": "FAIL"},
        {"routing-tests": "pending"}, autonomy_grant=_grant(),
    )
    assert result["decision"] == "HOLD"
    assert result["reason"] == "waiting_for_parent_jobs"
    assert result["waiting_job_ids"] == ["safe-review"]


def test_goal_planner_selects_child_after_dependency_is_done():
    result = plan_next_job(
        _goal(), {"line-routing": "PASS", "safe-execution": "FAIL"},
        {"routing-tests": "done"}, autonomy_grant=_grant(),
    )
    assert result["decision"] == "PROPOSE_CHILD_JOB"
    assert result["job"]["id"] == "safe-review"


def test_goal_planner_reports_goal_achieved_only_when_all_criteria_pass():
    result = plan_next_job(
        _goal(),
        {"line-routing": "PASS", "safe-execution": "PASS"},
        {"routing-tests": "done", "safe-review": "done"},
        autonomy_grant=_grant(),
    )
    assert result["decision"] == "GOAL_ACHIEVED"


def test_goal_planner_holds_when_criteria_are_unverified():
    result = plan_next_job(
        _goal(), {"line-routing": "PASS", "safe-execution": "UNKNOWN"}, {},
        autonomy_grant=_grant(),
    )
    assert result["decision"] == "HOLD"
    assert result["reason"] == "success_criteria_not_fully_verified"


def test_goal_planner_requires_review_for_protected_paths():
    goal = _goal()
    goal["jobs"][0]["allowed_paths"] = ["app.py", "tests/test_task_routing_line_development.py"]
    result = plan_next_job(goal, {"line-routing": "FAIL", "safe-execution": "FAIL"}, {}, autonomy_grant=_grant())
    assert result["decision"] == "HOLD"
    assert result["reason"] == "human_review_required_for_high_risk_job"
    assert result["approval_required_jobs"][0]["reason"] == "protected_path_requires_human_review"


def test_goal_planner_requires_review_for_operations_outside_granted_path_scope():
    grant = _grant()
    grant["allowed_path_prefixes"] = ["tests/"]
    goal = _goal()
    goal["jobs"][0]["stage"] = "design"
    goal["jobs"][0]["allowed_paths"] = ["docs/design.md"]
    result = plan_next_job(goal, {"line-routing": "FAIL", "safe-execution": "FAIL"}, {}, autonomy_grant=grant)
    assert result["decision"] == "HOLD"
    assert result["approval_required_jobs"][0]["reason"] == "outside_goal_autonomy_grant_scope"


def test_goal_planner_rejects_traversal_and_unbounded_path_patterns():
    for unsafe in ("../secrets.txt", "/etc/passwd", "tests/*.py", "tests/../docs/x.md"):
        goal = _goal()
        goal["jobs"][0]["allowed_paths"] = [unsafe]
        result = plan_next_job(goal, {"line-routing": "FAIL", "safe-execution": "FAIL"}, {}, autonomy_grant=_grant())
        assert result["decision"] == "HOLD"


def test_goal_planner_rejects_untrusted_authorization_claims():
    goal = _goal()
    goal["jobs"][0]["execution_approved"] = True
    result = plan_next_job(goal, {"line-routing": "FAIL", "safe-execution": "FAIL"}, {}, autonomy_grant=_grant())
    assert result["decision"] == "HOLD"
    assert result["reason"] == "untrusted_job_authorization_fields"


def test_goal_planner_rejects_unknown_dependencies_and_cycles():
    goal = _goal()
    goal["jobs"][0]["depends_on"] = ["missing"]
    assert plan_next_job(goal, {"line-routing": "FAIL", "safe-execution": "FAIL"}, {}, autonomy_grant=_grant())["reason"] == "job_dependency_unknown"

    goal = _goal()
    goal["jobs"][0]["depends_on"] = ["safe-review"]
    assert plan_next_job(goal, {"line-routing": "FAIL", "safe-execution": "FAIL"}, {}, autonomy_grant=_grant())["reason"] == "job_dependency_cycle"


def test_goal_planner_rejects_incomplete_evidence_and_malformed_job_fields():
    assert plan_next_job(_goal(), {"line-routing": "PASS"}, {}, autonomy_grant=_grant())["reason"] == "criterion_evidence_incomplete"

    goal = _goal()
    goal["jobs"][0]["criterion_id"] = ["line-routing"]
    assert plan_next_job(goal, {"line-routing": "FAIL", "safe-execution": "FAIL"}, {}, autonomy_grant=_grant())["decision"] == "HOLD"

    goal = _goal()
    goal["jobs"][0]["stage"] = ["test"]
    assert plan_next_job(goal, {"line-routing": "FAIL", "safe-execution": "FAIL"}, {}, autonomy_grant=_grant())["decision"] == "HOLD"


def test_goal_planner_stops_at_bounded_goal_job_budget():
    goal = _goal()
    goal["jobs"] = [
        {
            "id": f"job-{index}", "criterion_id": "line-routing",
            "stage": "test", "instruction": "Add a focused test.",
            "allowed_paths": ["tests/test_task_routing_line_development.py"],
            "depends_on": [],
        }
        for index in range(13)
    ]
    states = {f"job-{index}": "done" for index in range(12)}
    grant = _grant()
    grant["max_jobs"] = 12
    result = plan_next_job(goal, {"line-routing": "FAIL", "safe-execution": "FAIL"}, states, autonomy_grant=grant)
    assert result["decision"] == "HOLD"
    assert result["reason"] == "autonomy_job_budget_exhausted"


def test_goal_planner_rejects_expired_or_malformed_grants():
    grant = _grant()
    grant["expires_at"] = "2000-01-01T00:00:00Z"
    result = plan_next_job(_goal(), {"line-routing": "FAIL", "safe-execution": "FAIL"}, {}, autonomy_grant=grant)
    assert result["decision"] == "HOLD"
    assert result["reason"] == "autonomy_grant_invalid_or_mismatched"

    grant = _grant()
    grant["allowed_path_prefixes"] = [["tests/"]]
    result = plan_next_job(_goal(), {"line-routing": "FAIL", "safe-execution": "FAIL"}, {}, autonomy_grant=grant)
    assert result["decision"] == "HOLD"
    assert result["reason"] == "autonomy_grant_invalid_or_mismatched"


def test_goal_planner_rejects_test_stage_writing_outside_tests():
    goal = _goal()
    goal["jobs"][0]["allowed_paths"] = ["core/new_feature.py"]
    result = plan_next_job(goal, {"line-routing": "FAIL", "safe-execution": "FAIL"}, {}, autonomy_grant=_grant())
    assert result["decision"] == "HOLD"
    assert result["approval_required_jobs"][0]["reason"] == "test_stage_must_be_test_only"
