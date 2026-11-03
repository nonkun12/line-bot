from scripts.goal_job_chain import plan_next_job


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
                "depends_on": [], "execution_approved": True,
            },
            {
                "id": "safe-review", "criterion_id": "safe-execution",
                "stage": "review", "instruction": "Review evidence gates.",
                "allowed_paths": ["tests/test_creator_critic_diff_review.py"],
                "depends_on": ["routing-tests"], "execution_approved": True,
            },
        ],
    }


def test_goal_planner_proposes_first_approved_child_job_only():
    result = plan_next_job(
        _goal(),
        {"line-routing": "FAIL", "safe-execution": "FAIL"},
        {},
    )
    assert result["decision"] == "PROPOSE_CHILD_JOB"
    assert result["job"]["id"] == "routing-tests"
    assert result["create_job"] is False
    assert result["execute_job"] is False
    assert result["permissions"]["merge"] is False


def test_goal_planner_waits_for_parent_job_before_child():
    result = plan_next_job(
        _goal(),
        {"line-routing": "FAIL", "safe-execution": "FAIL"},
        {"routing-tests": "pending"},
    )
    assert result["decision"] == "PROPOSE_CHILD_JOB"
    assert result["job"]["id"] == "routing-tests"


def test_goal_planner_waits_for_dependency_to_complete():
    result = plan_next_job(
        _goal(),
        {"line-routing": "PASS", "safe-execution": "FAIL"},
        {"routing-tests": "done"},
    )
    assert result["decision"] == "PROPOSE_CHILD_JOB"
    assert result["job"]["id"] == "safe-review"


def test_goal_planner_reports_goal_achieved_only_when_all_criteria_pass():
    result = plan_next_job(
        _goal(),
        {"line-routing": "PASS", "safe-execution": "PASS"},
        {"routing-tests": "done", "safe-review": "done"},
    )
    assert result["decision"] == "GOAL_ACHIEVED"
    assert result["create_job"] is False


def test_goal_planner_holds_when_criteria_are_unverified():
    result = plan_next_job(
        _goal(),
        {"line-routing": "PASS", "safe-execution": "UNKNOWN"},
        {},
    )
    assert result["decision"] == "HOLD"
    assert result["reason"] == "success_criteria_not_fully_verified"


def test_goal_planner_requires_explicit_job_approval():
    goal = _goal()
    goal["jobs"][0]["execution_approved"] = False
    result = plan_next_job(
        goal,
        {"line-routing": "FAIL", "safe-execution": "FAIL"},
        {},
    )
    assert result["decision"] == "HOLD"
    assert result["reason"] == "human_approval_required"
    assert result["create_job"] is False


def test_goal_planner_rejects_unknown_dependencies_and_cycles():
    goal = _goal()
    goal["jobs"][0]["depends_on"] = ["missing"]
    assert plan_next_job(goal, {"line-routing": "FAIL", "safe-execution": "FAIL"}, {})["reason"] == "job_dependency_unknown"

    goal = _goal()
    goal["jobs"][0]["depends_on"] = ["safe-review"]
    assert plan_next_job(goal, {"line-routing": "FAIL", "safe-execution": "FAIL"}, {})["reason"] == "job_dependency_cycle"


def test_goal_planner_rejects_unsafe_paths_and_malformed_evidence():
    goal = _goal()
    goal["jobs"][0]["allowed_paths"] = ["../secrets.txt"]
    assert plan_next_job(goal, {"line-routing": "FAIL", "safe-execution": "FAIL"}, {})["decision"] == "HOLD"
    assert plan_next_job(_goal(), {"line-routing": "PASS"}, {})["reason"] == "criterion_evidence_incomplete"
