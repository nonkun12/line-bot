from core.ai_factory_stage426_430_exception_governance import (
    check_exception_approval_separation, check_exception_identity,
    check_exception_lifecycle, check_exception_scope_binding,
    evaluate_stages_426_430,
)


BASE = {
    "exception_id": "ex-1", "rationale": "documented compatibility issue",
    "scope_type": "workflow", "scope_id": "eval-v2", "requested_by": "actor-a",
    "approved_by": "actor-b", "decision": "approved", "decision_ref": "ticket-1",
    "valid_from": "2026-11-20T00:00:00Z", "expires_at": "2026-11-30T00:00:00Z",
    "revoked": False,
}


def test_426_requires_unique_scoped_exception_identity():
    assert check_exception_identity([BASE])["pass"]
    assert not check_exception_identity([BASE, BASE])["pass"]
    assert not check_exception_identity([{**BASE, "scope_id": "*"}])["pass"] is False


def test_427_rejects_self_approval_and_missing_decision():
    assert check_exception_approval_separation([BASE])["pass"]
    assert not check_exception_approval_separation([
        {**BASE, "approved_by": "actor-a"}
    ])["pass"]


def test_428_requires_current_timezone_aware_nonrevoked_window():
    assert check_exception_lifecycle([BASE], evaluated_at="2026-11-23T12:00:00Z")["pass"]
    assert not check_exception_lifecycle([
        {**BASE, "expires_at": "2026-11-22T00:00:00Z"}
    ], evaluated_at="2026-11-23T12:00:00Z")["pass"]
    assert not check_exception_lifecycle([BASE], evaluated_at="2026-11-23T12:00:00")["pass"]


def test_429_requires_exact_requested_scope_binding():
    assert check_exception_scope_binding(
        [BASE], [{"scope_type": "workflow", "scope_id": "eval-v2"}]
    )["pass"]
    assert not check_exception_scope_binding(
        [BASE], [{"scope_type": "workflow", "scope_id": "eval-v3"}]
    )["pass"]


def test_430_is_proposal_only_even_when_declarations_pass():
    result = evaluate_stages_426_430(
        exceptions=[BASE],
        requested_scopes=[{"scope_type": "workflow", "scope_id": "eval-v2"}],
        evaluated_at="2026-11-23T12:00:00Z",
    )
    assert result["status"] == "PASS"
    assert result["exception_activation_authorized"] is False
    assert result["execution_authorized"] is False
    assert result["promotion_authorized"] is False
    assert len(result["seal"]) == 64
    blocked = evaluate_stages_426_430(
        exceptions=[{**BASE, "revoked": True}],
        requested_scopes=[{"scope_type": "workflow", "scope_id": "eval-v2"}],
        evaluated_at="2026-11-23T12:00:00Z",
    )
    assert blocked["status"] == "BLOCKED"
    assert blocked["exception_activation_authorized"] is False
