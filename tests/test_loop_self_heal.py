from scripts.loop_self_heal import decide


def base(**overrides):
    value = {
        "task_id": "task-1",
        "fingerprint": "a" * 64,
        "category": "test_regression",
        "consecutive_failures": 1,
        "same_fingerprint_attempts": 0,
        "held": False,
        "base_sha": "b" * 40,
        "produced_sha": "c" * 40,
        "allowed_paths": ["tests/test_example.py"],
        "execution_authorized": True,
        "rea_status": "PRE_REPAIR_PASS",
    }
    value.update(overrides)
    return value


def test_requests_one_bounded_repair_only_with_scoped_authorization_and_rea():
    decision = decide(base())
    assert decision.action == "REPAIR_ONCE"
    assert decision.requires_rea is True
    assert decision.requires_human is False


def test_holds_when_task_is_held():
    assert decide(base(held=True)).action == "HOLD"


def test_holds_after_failure_budget_exhausted():
    assert decide(base(consecutive_failures=3)).reason == "failure_budget_exhausted"


def test_holds_when_repair_budget_is_exhausted():
    assert decide(base(same_fingerprint_attempts=1)).reason == "repair_preconditions_not_met"


def test_holds_when_allowed_path_escapes_repository():
    assert decide(base(allowed_paths=["../workflow.yml"])).action == "HOLD"


def test_transient_retry_requires_clean_unchanged_tree_and_allowlisted_code():
    evidence = base(
        category="transient",
        failure_code="provider_network_transient",
        base_sha="d" * 40,
        produced_sha="d" * 40,
        working_tree_clean=True,
        retry_count=0,
    )
    assert decide(evidence).action == "RETRY_TRANSIENT"
    assert decide({**evidence, "produced_sha": "e" * 40}).action == "HOLD"


def test_unknown_failure_fails_closed():
    assert decide(base(category="unknown")).action == "HOLD"


def test_invalid_identity_fails_closed():
    assert decide(base(fingerprint="not-a-fingerprint")).action == "HOLD"
