import goal_job_generation


def test_generator_creates_only_bounded_docs_followup_for_unmet_criterion():
    record = {
        "goal_id": "goal-demo",
        "goal": {
            "goal_id": "goal-demo",
            "objective": "Build an original game",
            "success_criteria": [{"id": "criterion", "description": "Plan is complete"}],
            "jobs": [{"id": "initial", "criterion_id": "criterion"}],
        },
        "autonomy_grant": {
            "active": True,
            "allowed_path_prefixes": ["docs/"],
            "allowed_stages": ["design"],
        },
    }
    job = goal_job_generation.generate_bounded_followup_job(
        record, {"criterion": "FAIL"}, {"initial": "failed"}
    )
    assert job["id"] == "goal-followup-002"
    assert job["criterion_id"] == "criterion"
    assert job["stage"] == "design"
    assert job["allowed_paths"] == ["docs/goal-plans/goal-demo/followup-002.md"]
    assert "writes only this documentation file" in job["instruction"]


def test_generator_does_not_duplicate_work_while_a_child_is_pending():
    record = {
        "goal_id": "goal-demo",
        "goal": {
            "goal_id": "goal-demo",
            "objective": "Build an original game",
            "success_criteria": [{"id": "criterion", "description": "Plan is complete"}],
            "jobs": [{"id": "initial", "criterion_id": "criterion"}],
        },
        "autonomy_grant": {
            "active": True,
            "allowed_path_prefixes": ["docs/"],
            "allowed_stages": ["design"],
        },
    }
    assert goal_job_generation.generate_bounded_followup_job(
        record, {"criterion": "FAIL"}, {"initial": "pending"}
    ) is None


def test_generator_fails_closed_without_docs_scope():
    record = {
        "goal_id": "goal-demo",
        "goal": {
            "goal_id": "goal-demo",
            "objective": "Build an original game",
            "success_criteria": [{"id": "criterion", "description": "Plan is complete"}],
            "jobs": [],
        },
        "autonomy_grant": {
            "active": True,
            "allowed_path_prefixes": ["tests/"],
            "allowed_stages": ["design"],
        },
    }
    assert goal_job_generation.generate_bounded_followup_job(
        record, {"criterion": "FAIL"}, {}
    ) is None
