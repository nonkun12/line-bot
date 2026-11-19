from scripts.goal_autopilot import evaluate_goal


VALID_SHA = "a" * 40


def completion_evidence(task_id):
    return {
        "task_id": task_id,
        "verified": True,
        "evidence_sha": VALID_SHA,
        "verification_ref": "run:123",
        "completed_at": "2026-11-19T00:00:00+00:00",
    }


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
        "id": "a", "verified": True, "evidence_ref": f"commit:{VALID_SHA}"
    }], tasks=[])
    assert evaluate_goal(g)["decision"] == "COMPLETE"


def test_verified_without_evidence_does_not_complete():
    g = goal(acceptance_criteria=[{"id": "a", "verified": True}], tasks=[])
    assert evaluate_goal(g)["decision"] == "HOLD"


def test_malformed_criterion_evidence_does_not_complete():
    for evidence_ref in ("zzz", "commit:abc123", "", None):
        g = goal(acceptance_criteria=[{
            "id": "a", "verified": True, "evidence_ref": evidence_ref
        }], tasks=[])
        assert evaluate_goal(g)["decision"] == "HOLD"


def test_duplicate_acceptance_criterion_ids_are_invalid():
    g = goal(acceptance_criteria=[
        {"id": "same", "verified": False},
        {"id": "same", "verified": True, "evidence_ref": f"commit:{VALID_SHA}"},
    ])
    assert evaluate_goal(g)["reason"] == "criterion_id_missing_or_duplicate"


def test_blank_acceptance_criterion_id_is_invalid():
    g = goal(acceptance_criteria=[{"id": "  ", "verified": False}])
    assert evaluate_goal(g)["reason"] == "criterion_id_missing_or_duplicate"


def test_kill_switch_holds_before_task_selection():
    assert evaluate_goal(goal(kill_switch=True))["reason"] == "kill_switch_active_or_invalid"


def test_non_boolean_kill_switch_values_fail_closed():
    for value in ("true", "false", 1, 0, None, [], {}):
        assert evaluate_goal(goal(kill_switch=value))["decision"] == "HOLD"


def test_missing_kill_switch_fails_closed():
    g = goal()
    del g["kill_switch"]
    assert evaluate_goal(g)["decision"] == "HOLD"


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


def test_dependency_order_requires_task_bound_completion_evidence():
    g = goal(tasks=[
        {"task_id": "later", "status": "PENDING", "kind": "TEST",
         "execution_authorized": True, "allowed_paths": [],
         "depends_on": ["first"]},
        {"task_id": "first", "status": "COMPLETED", "kind": "TEST",
         "completion_evidence": completion_evidence("first")},
    ])
    assert evaluate_goal(g)["task_id"] == "later"


def test_completed_label_without_evidence_cannot_unlock_dependency():
    g = goal(tasks=[
        {"task_id": "later", "status": "PENDING", "kind": "TEST",
         "execution_authorized": True, "allowed_paths": [],
         "depends_on": ["first"]},
        {"task_id": "first", "status": "COMPLETED", "kind": "TEST"},
    ])
    assert evaluate_goal(g)["reason"] == "completed_task_evidence_invalid"


def test_completion_evidence_must_be_bound_to_task_and_verified():
    for evidence in (
        {**completion_evidence("other"), "task_id": "other"},
        {**completion_evidence("first"), "verified": False},
        {**completion_evidence("first"), "evidence_sha": "bad"},
        {**completion_evidence("first"), "completed_at": "not-a-date"},
        {**completion_evidence("first"), "completed_at": "2026-11-19T00:00:00"},
    ):
        g = goal(tasks=[{
            "task_id": "first", "status": "COMPLETED", "kind": "TEST",
            "completion_evidence": evidence,
        }])
        assert evaluate_goal(g)["reason"] == "completed_task_evidence_invalid"


def test_forbidden_actions_are_held_even_if_marked_authorized():
    for kind in ("MERGE", "DEPLOY", "PERMISSION_CHANGE", "SECRET_CHANGE", "PRODUCTION_WRITE"):
        g = goal(tasks=[{
            "task_id": "danger", "status": "PENDING", "kind": kind,
            "execution_authorized": True, "allowed_paths": [],
        }])
        assert evaluate_goal(g)["reason"] == "action_kind_forbidden"


def test_unapproved_task_is_held():
    g = goal(tasks=[{
        "task_id": "t1", "status": "PENDING", "kind": "DRAFT_PR",
        "execution_authorized": False, "allowed_paths": ["src/"],
    }])
    assert evaluate_goal(g)["reason"] == "draft_pr_requires_explicit_task_authorization"


def test_duplicate_task_ids_are_invalid():
    g = goal(tasks=[
        {"task_id": "x", "status": "PENDING", "kind": "TEST"},
        {"task_id": "x", "status": "PENDING", "kind": "TEST"},
    ])
    assert evaluate_goal(g)["decision"] == "INVALID"


def test_unknown_dependency_is_invalid():
    g = goal(tasks=[{
        "task_id": "x", "status": "PENDING", "kind": "TEST",
        "execution_authorized": True, "allowed_paths": [],
        "depends_on": ["missing"],
    }])
    assert evaluate_goal(g)["decision"] == "INVALID"


def test_self_referential_dependency_is_invalid():
    g = goal(tasks=[{
        "task_id": "x", "status": "PENDING", "kind": "TEST",
        "execution_authorized": True, "allowed_paths": [],
        "depends_on": ["x"],
    }])
    assert evaluate_goal(g)["reason"] == "task_dependencies_duplicate_or_self_referential"


def test_duplicate_dependencies_are_invalid():
    g = goal(tasks=[
        {"task_id": "x", "status": "PENDING", "kind": "TEST",
         "execution_authorized": True, "allowed_paths": [],
         "depends_on": ["done", "done"]},
        {"task_id": "done", "status": "COMPLETED", "kind": "TEST",
         "completion_evidence": completion_evidence("done")},
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


def test_deep_dependency_chain_does_not_raise_recursion_error():
    tasks = []
    for i in range(500):
        task = {"task_id": f"t{i}", "status": "PENDING", "kind": "READ_ONLY",
                "execution_authorized": True, "allowed_paths": []}
        if i:
            task["depends_on"] = [f"t{i-1}"]
        tasks.append(task)
    g = goal(tasks=tasks)
    result = evaluate_goal(g)
    assert result["decision"] == "CONTINUE"
    assert result["task_id"] == "t0"


def test_task_count_is_bounded():
    g = goal(tasks=[
        {"task_id": f"t{i}", "status": "PENDING", "kind": "READ_ONLY"}
        for i in range(501)
    ])
    assert evaluate_goal(g)["reason"] == "task_count_exceeds_limit"


def test_path_traversal_is_held():
    g = goal(tasks=[{
        "task_id": "t1", "status": "PENDING", "kind": "TEST",
        "execution_authorized": True, "allowed_paths": ["tests/../../.github"],
    }])
    assert evaluate_goal(g)["reason"] == "allowed_paths_invalid"


def test_absolute_and_windows_paths_are_held():
    for path in ("/etc/passwd", r"..\\secrets", "C:/secrets"):
        g = goal(tasks=[{
            "task_id": "t1", "status": "PENDING", "kind": "TEST",
            "execution_authorized": True, "allowed_paths": [path],
        }])
        assert evaluate_goal(g)["reason"] == "allowed_paths_invalid"


def test_whitespace_and_colon_paths_are_held():
    for path in (" /etc/passwd", "tests/ ..", "tests/file:stream"):
        g = goal(tasks=[{
            "task_id": "t1", "status": "PENDING", "kind": "TEST",
            "execution_authorized": True, "allowed_paths": [path],
        }])
        assert evaluate_goal(g)["reason"] == "allowed_paths_invalid"


def test_protected_paths_are_held():
    for path in (".github/workflows/", ".git/hooks/", "CODEOWNERS",
                 ".env", "config/secrets/token.txt", ".aws/credentials", ".netrc", ".npmrc", ".pypirc", ".git-credentials"):
        g = goal(tasks=[{
            "task_id": "t1", "status": "PENDING", "kind": "TEST",
            "execution_authorized": True, "allowed_paths": [path],
        }])
        assert evaluate_goal(g)["reason"] == "allowed_paths_invalid"


def test_repeated_trailing_separators_are_rejected():
    for path in ("src//", "tests///", "src//module.py"):
        g = goal(tasks=[{
            "task_id": "t1", "status": "PENDING", "kind": "TEST",
            "execution_authorized": True, "allowed_paths": [path],
        }])
        assert evaluate_goal(g)["reason"] == "allowed_paths_invalid"


def test_draft_pr_requires_explicit_nonempty_paths():
    g = goal(tasks=[{
        "task_id": "t1", "status": "PENDING", "kind": "DRAFT_PR",
        "execution_authorized": True, "allowed_paths": [],
    }])
    assert evaluate_goal(g)["reason"] == "draft_pr_requires_explicit_paths"


def test_dependencies_are_validated_even_for_completed_tasks():
    g = goal(tasks=[
        {"task_id": "done", "status": "COMPLETED", "kind": "TEST",
         "completion_evidence": completion_evidence("done"),
         "depends_on": ["missing"]},
        {"task_id": "next", "status": "PENDING", "kind": "TEST",
         "execution_authorized": True, "allowed_paths": []},
    ])
    assert evaluate_goal(g)["decision"] == "INVALID"


def test_malformed_unhashable_status_is_invalid_not_exception():
    g = goal(tasks=[{
        "task_id": "t1", "status": ["PENDING"], "kind": "TEST",
        "execution_authorized": True, "allowed_paths": [],
    }])
    assert evaluate_goal(g)["reason"] == "unsupported_task_status"


def test_malformed_unhashable_action_kind_is_held_not_exception():
    g = goal(tasks=[{
        "task_id": "t1", "status": "PENDING", "kind": ["DEPLOY"],
        "execution_authorized": True, "allowed_paths": [],
    }])
    assert evaluate_goal(g)["reason"] == "action_kind_not_allowlisted"


def test_acceptance_criteria_cannot_mark_goal_complete_with_incomplete_tasks():
    g = goal(
        acceptance_criteria=[{
            "id": "a", "verified": True, "evidence_ref": f"commit:{VALID_SHA}",
        }],
        tasks=[{
            "task_id": "pending", "status": "PENDING", "kind": "READ_ONLY",
            "execution_authorized": True, "allowed_paths": [],
        }],
    )
    assert evaluate_goal(g)["reason"] == "acceptance_criteria_met_but_tasks_incomplete"


def test_complete_requires_all_tasks_to_have_valid_completion_evidence():
    g = goal(
        acceptance_criteria=[{
            "id": "a", "verified": True, "evidence_ref": f"commit:{VALID_SHA}",
        }],
        tasks=[{
            "task_id": "done", "status": "COMPLETED", "kind": "READ_ONLY",
            "completion_evidence": completion_evidence("done"),
        }],
    )
    assert evaluate_goal(g)["decision"] == "COMPLETE"


def test_approved_code_change_kind_is_selectable_with_scoped_paths():
    g = goal(tasks=[{
        "task_id": "scoped-code-change", "status": "PENDING", "kind": "CODE_CHANGE",
        "execution_authorized": True, "allowed_paths": ["src/module.py"],
    }])
    assert evaluate_goal(g)["decision"] == "CONTINUE"
