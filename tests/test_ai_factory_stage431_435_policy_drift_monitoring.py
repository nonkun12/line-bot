from core.ai_factory_stage431_435_policy_drift_monitoring import (
    check_drift_disposition, check_policy_snapshot, classify_policy_drift,
    compare_policy_snapshots, evaluate_stages_431_435,
)


def snapshot(version, rules):
    return {"policy_id": "guardrails", "version": version, "effective_at": "2026-11-23T00:00:00Z",
            "owner": "policy-team", "canonical_digest": "a" * 64, "rules": rules}


def test_431_snapshot_requires_valid_rule_identity_and_digest():
    good = snapshot("1", [{"rule_id": "r1", "mode": "deny"}])
    assert check_policy_snapshot(good)["pass"]
    assert not check_policy_snapshot({**good, "canonical_digest": "bad"})["pass"]


def test_432_compares_added_removed_and_changed_rules():
    result = compare_policy_snapshots(
        snapshot("1", [{"rule_id": "a", "mode": "deny"}, {"rule_id": "b", "mode": "allow"}]),
        snapshot("2", [{"rule_id": "a", "mode": "review"}, {"rule_id": "c", "mode": "deny"}]),
    )
    assert result["pass"]
    assert result["added"] == ["c"]
    assert result["removed"] == ["b"]
    assert result["changed"] == ["a"]


def test_433_requires_classification_for_every_drift():
    diff = {"added": ["a"], "removed": [], "changed": ["b"]}
    assert classify_policy_drift(diff, {"a": "low", "b": "high"})["pass"]
    assert not classify_policy_drift(diff, {"a": "low"})["pass"]


def test_434_requires_traceable_disposition_and_escalates_high_risk():
    diff = {"added": ["r1"], "removed": [], "changed": []}
    classes = {"r1": "critical"}
    assert not check_drift_disposition(
        diff, classes, {"r1": {"decision": "accept_for_review", "owner": "x", "decision_ref": "ticket"}}
    )["pass"]
    assert check_drift_disposition(
        diff, classes, {"r1": {"decision": "defer", "owner": "x", "decision_ref": "ticket"}}
    )["pass"]


def test_435_fail_closed_and_never_applies_policy_or_authorizes_execution():
    old = snapshot("1", [{"rule_id": "r1", "mode": "deny"}])
    new = snapshot("2", [{"rule_id": "r1", "mode": "review"}])
    result = evaluate_stages_431_435(
        previous=old, current=new, classifications={"r1": "medium"},
        dispositions={"r1": {"decision": "defer", "owner": "policy-team", "decision_ref": "audit-1"}},
    )
    assert result["status"] == "PASS"
    assert result["policy_apply_authorized"] is False
    assert result["execution_authorized"] is False
    assert result["promotion_authorized"] is False
    assert len(result["seal"]) == 64
    blocked = evaluate_stages_431_435(previous=old, current=new, classifications={}, dispositions={})
    assert blocked["status"] == "BLOCKED"
