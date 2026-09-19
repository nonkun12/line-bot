from __future__ import annotations

from dataclasses import replace

import pytest

from core.management_safety import (
    CapabilityGrant,
    GateDecision,
    ManagementGateInput,
    ManagementPlan,
    evaluate_management_gate,
)


def build_plan(**kwargs: object) -> ManagementPlan:
    values = {
        "task_id": "task-1",
        "origin": "trusted",
        "intent": "add regression test",
        "scope_paths": ("tests/test_example.py",),
        "max_files": 2,
        "max_changes": 80,
        "rollback_plan": "revert the branch commit",
        "budget_calls": 5,
        "budget_units": 20,
        "ttl_seconds": 600,
        "parent_task": "human-1",
        "tainted": False,
        "delegation_depth": 1,
        "retries": 1,
    }
    values.update(kwargs)
    return ManagementPlan(**values)


def build_request(plan: ManagementPlan | None = None, **kwargs: object) -> ManagementGateInput:
    plan = plan or build_plan()
    values = {
        "plan": plan,
        "approved_plan_hash": plan.plan_hash(),
        "base_sha": "base123",
        "expected_base_sha": "base123",
        "head_sha": "head456",
        "diff_hash": "diff789",
        "changed_paths": ("tests/test_example.py",),
        "changed_files": 1,
        "changed_lines": 12,
        "tests_passed": True,
        "reviewed": True,
        "review_sha": "head456",
        "rollback_verified": True,
        "policy_version": "management-safety-v1",
        "now_epoch": 1000,
        "approval_expires_at": 1200,
    }
    values.update(kwargs)
    return ManagementGateInput(**values)


def test_allow_requires_all_deterministic_evidence() -> None:
    result = evaluate_management_gate(build_request())
    assert result.decision is GateDecision.ALLOW


def test_plan_hash_mismatch_is_denied() -> None:
    request = build_request(approved_plan_hash="wrong")
    result = evaluate_management_gate(request)
    assert result.decision is GateDecision.DENY
    assert "plan hash" in result.reasons[0]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tests_passed", False),
        ("rollback_verified", False),
        ("policy_version", "old-policy"),
        ("base_sha", "other-base"),
        ("review_sha", "other-head"),
    ],
)
def test_integrity_failures_are_denied(field: str, value: object) -> None:
    request = build_request(**{field: value})
    result = evaluate_management_gate(request)
    assert result.decision is GateDecision.DENY


def test_protected_control_plane_needs_human() -> None:
    request = build_request(changed_paths=("core/control_tower.py",))
    result = evaluate_management_gate(request)
    assert result.decision is GateDecision.NEEDS_HUMAN


def test_tainted_external_input_needs_human() -> None:
    plan = build_plan(origin="untrusted", tainted=True)
    result = evaluate_management_gate(build_request(plan))
    assert result.decision is GateDecision.NEEDS_HUMAN


def test_dependency_or_network_change_needs_human() -> None:
    result = evaluate_management_gate(
        build_request(changes_dependencies=True, introduces_external_network=True)
    )
    assert result.decision is GateDecision.NEEDS_HUMAN


def test_review_must_bind_to_exact_head_sha() -> None:
    result = evaluate_management_gate(build_request(review_sha="different"))
    assert result.decision is GateDecision.DENY


def test_changed_paths_and_counts_must_agree() -> None:
    result = evaluate_management_gate(build_request(changed_files=2))
    assert result.decision is GateDecision.DENY


def test_capability_attenuation_cannot_expand_scope_or_expiry() -> None:
    parent = CapabilityGrant(
        issuer="human",
        subject="management",
        scopes=frozenset({"tests/", "docs/"}),
        issued_at=100,
        expires_at=500,
        parent_task="task-1",
        nonce="parent",
    )
    child = parent.attenuate(
        subject="english-agent",
        scopes={"tests/"},
        expires_at=400,
        nonce="child",
    )
    assert child.scopes == frozenset({"tests/"})
    assert child.expires_at == 400
    assert child.issuer == "management"
    with pytest.raises(ValueError):
        parent.attenuate(
            subject="english-agent",
            scopes={"src/"},
            expires_at=400,
            nonce="bad-scope",
        )
    with pytest.raises(ValueError):
        parent.attenuate(
            subject="english-agent",
            scopes={"tests/"},
            expires_at=600,
            nonce="bad-expiry",
        )


def test_plan_hash_changes_when_scope_changes() -> None:
    plan = build_plan()
    changed = replace(plan, scope_paths=("tests/test_other.py",))
    assert changed.plan_hash() != plan.plan_hash()
