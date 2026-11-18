from scripts.goal_autopilot import evaluate_goal


def goal(**overrides):
    value = {
        "goal_id": "goal-1",
        "objective": "Deliver the defined outcome",
        "acceptance_criteria": [{"id": "a", "verified": False}],
        "safety_gate": True,
        "kill_switch": False,
        "tasks": [
            {"task_id": "t1", "status": "PENDING", "kind": "TEST",
             "execution_authorized": True, "allowed_paths": ["tests/"]},
            {"task_id": "t2", "status": "PENDING", "kind": "READ_ONLY",
             "execution_authorized": True, "allowed_paths": []},
        ],
    }
    value.update(overrides)
    return value


def test_selects_one_authorized_task_and_is_deterministic():
    result = evaluate_goal(goal())
    assert result == {
        "decision": "CONTINUE", "reason": "next_task_selected",
        "task_id": "t1", "kind": "TEST",
        "allowed_paths": ["tests/"], "max_tasks": 1,
    }


def test_goal_completes_only_with_verified_criteria_and_evidence():
    g = goal(acceptance_criteria=[{
        "id": "a", "verified": True, "evidence_ref": "commit:abc123"
    }], tasks=[])
    assert evaluate_goal(g)["decision"] == "COMPLETE"


def test_verified_without_evidence_does_not_complete():
    g = goal(acceptance_criteria=[{"id": "a", "verified": True}], tasks=[])
    assert evaluate_goal(g)["decision"] == "HOLD"


def test_duplicate_acceptance_criterion_ids_are_invalid():
    g = goal(acceptance_criteria=[
        {"id": "same", "verified": False},
        {"id": "same", "verified": True, "evidence_ref": "commit:abc123"},
    ])
    assert evaluate_goal(g)["reason"] == "criterion_id_missing_or_duplicate"


def test_blank_acceptance_criterion_id_is_invalid():
    g = goal(acceptance_criteria=[{"id": "  ", "verified": False}])
    assert evaluate_goal(g)["reason"] == "criterion_id_missing_or_duplicate"


def test_kill_switch_holds_before_task_selection():
    assert evaluate_goal(goal(kill_switch=True))["reason"] == "kill_switch_active"


def test_missing_safety_gate_fails_closed():
    assert evaluate_goal(goal(safety_gate=False))["decision"] == "HOLD"


def test_in_flight_task_must_be_reconciled_before_new_work():
    g = goal(tasks=[
        {"task_id": "t0", "status": "IN_PROGRESS", "kind": "TEST"},
        {"task_id": "t1", "status": "PENDING", "kind": "TEST",
         "execution_authorized": True, "allowed_paths": []},
    ])
    assert evaluate_goal(g)["reason"] == "in_flight_task_requires_reconciliation"


def test_failed_or_held_tasks_are_never_silently_retried():
    g = goal(tasks=[
        {"task_id": "t0", "status": "FAILED", "kind": "TEST"},
        {"task_id": "t1", "status": "PENDING", "kind": "TEST",
         "execution_authorized": True, "allowed_paths": []},
    ])
    assert evaluate_goal(g)["reason"] == "failed_or_held_task_requires_review"


def test_dependency_order_is_enforced():
    g = goal(tasks=[
        {"task_id": "later", "status": "PENDING", "kind": "TEST",
         "execution_authorized": True, "allowed_paths": [],
         "depends_on": ["first"]},
        {"task_id": "first", "status": "COMPLETED", "kind": "TEST"},
    ])
    assert evaluate_goal(g)["task_id"] == "later"


def test_forbidden_actions_are_held_even_if_marked_authorized():
    g = goal(tasks=[
        {"task_id": "danger", "status": "PENDING", "kind": "DEPLOY",
         "execution_authorized": True, "allowed_paths": []}
    ])
    assert evaluate_goal(g)["reason"] == "action_kind_forbidden"


def test_unapproved_task_is_held():
    g = goal(tasks=[
        {"task_id": "t1", "status": "PENDING", "kind": "DRAFT_PR",
         "execution_authorized": False, "allowed_paths": ["src/"]}
    ])
    assert evaluate_goal(g)["reason"] == "draft_pr_requires_explicit_task_authorization"


def test_duplicate_task_ids_are_invalid():
    g = goal(tasks=[
        {"task_id": "x", "status": "PENDING", "kind": "TEST"},
        {"task_id": "x", "status": "PENDING", "kind": "TEST"},
    ])
    assert evaluate_goal(g)["decision"] == "INVALID"


def test_unknown_dependency_is_invalid():
    g = goal(tasks=[
        {"task_id": "x", "status": "PENDING", "kind": "TEST",
         "execution_authorized": True, "allowed_paths": [],
         "depends_on": ["missing"]}
    ])
    assert evaluate_goal(g)["decision"] == "INVALID"


def test_self_referential_dependency_is_invalid():
    g = goal(tasks=[
        {"task_id": "x", "status": "PENDING", "kind": "TEST",
         "execution_authorized": True, "allowed_paths": [],
         "depends_on": ["x"]}
    ])
    assert evaluate_goal(g)["reason"] == "task_dependencies_duplicate_or_self_referential"


def test_duplicate_dependencies_are_invalid():
    g = goal(tasks=[
        {"task_id": "x", "status": "PENDING", "kind": "TEST",
         "execution_authorized": True, "allowed_paths": [],
         "depends_on": ["done", "done"]},
        {"task_id": "done", "status": "COMPLETED", "kind": "TEST"},
    ])
    assert evaluate_goal(g)["reason"] == "task_dependencies_duplicate_or_self_referential"


def test_cyclic_dependencies_are_invalid():
    g = goal(tasks=[
        {"task_id": "x", "status": "PENDING", "kind": "TEST",
         "execution_authorized": True, "allowed_paths": [], "depends_on": ["y"]},
        {"task_id": "y", "status": "PENDING", "kind": "TEST",
         "execution_authorized": True, "allowed_paths": [], "depends_on": ["x"]},
    ])
    assert evaluate_goal(g)["reason"] == "cyclic_task_dependencies"


def test_path_traversal_is_held():
    g = goal(tasks=[{
        "task_id": "t1", "status": "PENDING", "kind": "TEST",
        "execution_authorized": True, "allowed_paths": ["tests/../../.github"]
    }])
    assert evaluate_goal(g)["reason"] == "allowed_paths_invalid"


def test_absolute_and_windows_paths_are_held():
    for path in ("/etc/passwd", r"..\secrets", "C:/secrets"):
        g = goal(tasks=[{
            "task_id": "t1", "status": "PENDING", "kind": "TEST",
            "execution_authorized": True, "allowed_paths": [path]
        }])
        assert evaluate_goal(g)["reason"] == "allowed_paths_invalid"


def test_dependencies_are_validated_even_for_completed_tasks():
    g = goal(tasks=[
        {"task_id": "done", "status": "COMPLETED", "kind": "TEST",
         "depends_on": ["missing"]},
        {"task_id": "next", "status": "PENDING", "kind": "TEST",
         "execution_authorized": True, "allowed_paths": []},
    ])
    assert evaluate_goal(g)["decision"] == "INVALID"
